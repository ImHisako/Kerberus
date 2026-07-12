package main

import (
	"bufio"
	"encoding/base64"
	"encoding/binary"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"net"
	"os"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

const maxFrame = 4_000_000

type command struct {
	ID          string `json:"id,omitempty"`
	Op          string `json:"op"`
	Destination string `json:"destination,omitempty"`
	Stream      string `json:"stream,omitempty"`
	Payload     string `json:"payload,omitempty"`
}

type response struct {
	ID          string `json:"id,omitempty"`
	OK          bool   `json:"ok,omitempty"`
	Error       string `json:"error,omitempty"`
	Event       string `json:"event,omitempty"`
	Destination string `json:"destination,omitempty"`
	Stream      string `json:"stream,omitempty"`
	Payload     string `json:"payload,omitempty"`
}

type peerStream struct {
	destination string
	token       string
	inbound     bool
	conn        net.Conn
	writeMu     sync.Mutex
}

type bridge struct {
	host            string
	session         string
	streamsMu       sync.Mutex
	outbound        map[string]*peerStream
	byToken         map[string]*peerStream
	nextToken       atomic.Uint64
	stop            chan struct{}
	stopOnce        sync.Once
	outputMu        sync.Mutex
	output          *json.Encoder
	lastAcceptError string
	acceptErrorMu   sync.Mutex
}

func main() {
	host := flag.String("host", "127.0.0.1", "SAM host")
	port := flag.String("port", "7656", "SAM port")
	session := flag.String("session", "", "existing SAM session id")
	flag.Parse()
	if *session == "" {
		os.Exit(2)
	}
	b := &bridge{
		host:     net.JoinHostPort(*host, *port),
		session:  *session,
		outbound: make(map[string]*peerStream),
		byToken:  make(map[string]*peerStream),
		stop:     make(chan struct{}),
		output:   json.NewEncoder(os.Stdout),
	}
	// SAM 3.2 supports concurrent pending ACCEPTs. Matching the configured
	// inbound tunnel quantity avoids a single accept socket becoming a queue.
	for range 3 {
		go b.acceptLoop()
	}
	scanner := bufio.NewScanner(os.Stdin)
	scanner.Buffer(make([]byte, 4096), 8*1024*1024)
	for scanner.Scan() {
		var cmd command
		if err := json.Unmarshal(scanner.Bytes(), &cmd); err != nil {
			continue
		}
		if cmd.Op == "stop" {
			b.close()
			return
		}
		err := b.handle(cmd)
		if cmd.ID != "" {
			out := response{ID: cmd.ID, OK: err == nil}
			if err != nil {
				out.Error = err.Error()
			}
			b.emit(out)
		}
	}
	b.close()
}

func (b *bridge) handle(cmd command) error {
	if cmd.Op != "send" && cmd.Op != "reply" && cmd.Op != "warm" {
		return errors.New("operazione non supportata")
	}
	payload, err := decodePayload(cmd.Payload)
	if cmd.Op == "reply" {
		if err != nil || cmd.Stream == "" {
			return errors.New("risposta non valida")
		}
		b.streamsMu.Lock()
		stream := b.byToken[cmd.Stream]
		b.streamsMu.Unlock()
		if stream == nil {
			return errors.New("stream non più disponibile")
		}
		if err := stream.writeFrame(payload); err != nil {
			b.drop(stream)
			return err
		}
		return nil
	}
	if cmd.Destination == "" {
		return errors.New("destination mancante")
	}
	if !validDestination(cmd.Destination) {
		return errors.New("destination I2P non valida")
	}
	stream, err := b.stream(cmd.Destination)
	if err != nil {
		return err
	}
	if cmd.Op == "warm" {
		return nil
	}
	if err != nil {
		return errors.New("payload non valido")
	}
	if err := stream.writeFrame(payload); err == nil {
		return nil
	}
	b.drop(stream)
	stream, err = b.stream(cmd.Destination)
	if err != nil {
		return err
	}
	return stream.writeFrame(payload)
}

func (b *bridge) stream(destination string) (*peerStream, error) {
	b.streamsMu.Lock()
	if stream := b.outbound[destination]; stream != nil {
		b.streamsMu.Unlock()
		return stream, nil
	}
	b.streamsMu.Unlock()
	conn, err := net.DialTimeout("tcp", b.host, 15*time.Second)
	if err != nil {
		return nil, err
	}
	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetNoDelay(true)
		_ = tcp.SetKeepAlive(true)
		_ = tcp.SetKeepAlivePeriod(30 * time.Second)
	}
	reader := bufio.NewReader(conn)
	if err := writeLine(conn, "HELLO VERSION MIN=3.1 MAX=3.3"); err != nil {
		conn.Close()
		return nil, err
	}
	line, err := reader.ReadString('\n')
	if err != nil || !strings.Contains(line, "RESULT=OK") {
		conn.Close()
		return nil, fmt.Errorf("handshake SAM fallito: %s", strings.TrimSpace(line))
	}
	// No status round-trip: the first frame written just after this command may
	// be bundled into the I2P Streaming SYN by connectDelay.
	if err := writeLine(conn, fmt.Sprintf("STREAM CONNECT ID=%s DESTINATION=%s SILENT=true", b.session, destination)); err != nil {
		conn.Close()
		return nil, err
	}
	stream := &peerStream{destination: destination, token: b.token("out"), conn: conn}
	b.streamsMu.Lock()
	if current := b.outbound[destination]; current != nil {
		b.streamsMu.Unlock()
		conn.Close()
		return current, nil
	}
	b.outbound[destination] = stream
	b.byToken[stream.token] = stream
	b.streamsMu.Unlock()
	go b.readFrames(stream, reader)
	return stream, nil
}

func (s *peerStream) writeFrame(payload []byte) error {
	s.writeMu.Lock()
	defer s.writeMu.Unlock()
	header := make([]byte, 4)
	binary.BigEndian.PutUint32(header, uint32(len(payload)))
	if err := writeAll(s.conn, header); err != nil {
		return err
	}
	return writeAll(s.conn, payload)
}

func (b *bridge) readFrames(stream *peerStream, reader *bufio.Reader) {
	for {
		var size uint32
		if err := binary.Read(reader, binary.BigEndian, &size); err != nil {
			break
		}
		if size > maxFrame {
			break
		}
		payload := make([]byte, size)
		if _, err := io.ReadFull(reader, payload); err != nil {
			break
		}
		b.emit(response{
			Event:       "frame",
			Destination: stream.destination,
			Stream:      stream.token,
			Payload:     base64.StdEncoding.EncodeToString(payload),
		})
	}
	b.drop(stream)
}

func (b *bridge) emit(value response) {
	b.outputMu.Lock()
	defer b.outputMu.Unlock()
	_ = b.output.Encode(value)
}

func (b *bridge) drop(expected *peerStream) {
	b.streamsMu.Lock()
	if b.outbound[expected.destination] == expected {
		delete(b.outbound, expected.destination)
	}
	if b.byToken[expected.token] == expected {
		delete(b.byToken, expected.token)
	}
	b.streamsMu.Unlock()
	_ = expected.conn.Close()
}

func (b *bridge) close() {
	b.stopOnce.Do(func() { close(b.stop) })
	b.streamsMu.Lock()
	streams := make([]*peerStream, 0, len(b.byToken))
	for _, stream := range b.byToken {
		streams = append(streams, stream)
	}
	b.outbound = make(map[string]*peerStream)
	b.byToken = make(map[string]*peerStream)
	b.streamsMu.Unlock()
	for _, stream := range streams {
		_ = stream.conn.Close()
	}
}

func (b *bridge) acceptLoop() {
	for {
		select {
		case <-b.stop:
			return
		default:
		}
		if err := b.acceptOne(); err != nil {
			b.reportAcceptError(err)
			select {
			case <-b.stop:
				return
			case <-time.After(300 * time.Millisecond):
			}
		}
	}
}

func (b *bridge) reportAcceptError(err error) {
	message := err.Error()
	b.acceptErrorMu.Lock()
	if message == b.lastAcceptError {
		b.acceptErrorMu.Unlock()
		return
	}
	b.lastAcceptError = message
	b.acceptErrorMu.Unlock()
	b.emit(response{Event: "accept_error", Error: message})
}

func (b *bridge) acceptOne() error {
	conn, err := net.DialTimeout("tcp", b.host, 15*time.Second)
	if err != nil {
		return err
	}
	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetNoDelay(true)
		_ = tcp.SetKeepAlive(true)
		_ = tcp.SetKeepAlivePeriod(30 * time.Second)
	}
	reader := bufio.NewReader(conn)
	if err := writeLine(conn, "HELLO VERSION MIN=3.1 MAX=3.3"); err != nil {
		conn.Close()
		return err
	}
	if line, err := reader.ReadString('\n'); err != nil || !strings.Contains(line, "RESULT=OK") {
		conn.Close()
		return fmt.Errorf("handshake SAM accept fallito: %s", strings.TrimSpace(line))
	}
	if err := writeLine(conn, fmt.Sprintf("STREAM ACCEPT ID=%s SILENT=false", b.session)); err != nil {
		conn.Close()
		return err
	}
	if line, err := reader.ReadString('\n'); err != nil || !strings.Contains(line, "RESULT=OK") {
		conn.Close()
		return fmt.Errorf("accept SAM fallito: %s", strings.TrimSpace(line))
	}
	remote, err := reader.ReadString('\n')
	if err != nil {
		conn.Close()
		return err
	}
	fields := strings.Fields(remote)
	if len(fields) == 0 {
		conn.Close()
		return errors.New("destination remota mancante")
	}
	// SAM 3.2 may append FROM_PORT and TO_PORT after the public destination.
	remote = fields[0]
	if !validDestination(remote) {
		conn.Close()
		return errors.New("destination remota non valida")
	}
	stream := &peerStream{
		destination: remote,
		token:       b.token("in"),
		inbound:     true,
		conn:        conn,
	}
	b.registerInbound(stream)
	go b.readFrames(stream, reader)
	return nil
}

func (b *bridge) registerInbound(stream *peerStream) {
	b.streamsMu.Lock()
	defer b.streamsMu.Unlock()
	b.byToken[stream.token] = stream
	// I2P Streaming is full-duplex. Reuse the accepted stream for application
	// replies instead of paying for a second CONNECT in the reverse direction.
	if b.outbound[stream.destination] == nil {
		b.outbound[stream.destination] = stream
	}
}

func (b *bridge) token(prefix string) string {
	return fmt.Sprintf("%s-%d", prefix, b.nextToken.Add(1))
}

func decodePayload(encoded string) ([]byte, error) {
	payload, err := base64.StdEncoding.DecodeString(encoded)
	if err != nil || len(payload) > maxFrame {
		return nil, errors.New("payload non valido")
	}
	return payload, nil
}

func writeLine(writer io.Writer, line string) error {
	return writeAll(writer, []byte(line+"\n"))
}

func writeAll(writer io.Writer, data []byte) error {
	for len(data) > 0 {
		written, err := writer.Write(data)
		if err != nil {
			return err
		}
		if written == 0 {
			return io.ErrShortWrite
		}
		data = data[written:]
	}
	return nil
}

func validDestination(value string) bool {
	if len(value) < 1 || len(value) > 4096 {
		return false
	}
	for _, char := range value {
		if (char >= 'a' && char <= 'z') || (char >= 'A' && char <= 'Z') ||
			(char >= '0' && char <= '9') || strings.ContainsRune("=._~-", char) {
			continue
		}
		return false
	}
	return true
}
