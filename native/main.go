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
	ID          string         `json:"id,omitempty"`
	OK          bool           `json:"ok,omitempty"`
	Error       string         `json:"error,omitempty"`
	Event       string         `json:"event,omitempty"`
	Destination string         `json:"destination,omitempty"`
	Stream      string         `json:"stream,omitempty"`
	Payload     string         `json:"payload,omitempty"`
	Metrics     *timingMetrics `json:"metrics,omitempty"`
}

type timingMetrics struct {
	QueueWaitUS         int64 `json:"queue_wait_us,omitempty"`
	HandlerUS           int64 `json:"handler_us,omitempty"`
	SAMHandshakeUS      int64 `json:"sam_handshake_us,omitempty"`
	SAMConnectCommandUS int64 `json:"sam_connect_command_us,omitempty"`
	I2PStreamOpenUS     int64 `json:"i2p_stream_open_us,omitempty"`
	ColdStream          bool  `json:"cold_stream"`
}

type commandWork struct {
	command  command
	enqueued time.Time
}

type contactWorker struct {
	mu     sync.Mutex
	ready  *sync.Cond
	queue  []commandWork
	closed bool
}

type commandDispatcher struct {
	key     func(command) string
	handle  func(command) (timingMetrics, error)
	emit    func(response)
	workers map[string]*contactWorker
	wg      sync.WaitGroup
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
	voiceEncode := flag.Bool("voice-encode", false, "encode PCM from stdin as a Kerberus voice message")
	voiceDecode := flag.Bool("voice-decode", false, "decode a Kerberus voice message from stdin to PCM")
	voiceInputRate := flag.Int("sample-rate", voiceSampleRate, "voice input sample rate")
	voiceInputChannels := flag.Int("channels", 1, "voice input channel count")
	voiceInputFormat := flag.String("sample-format", "s16le", "voice input format: u8, s16le, s32le, f32le")
	flag.Parse()
	if *voiceEncode || *voiceDecode {
		if *voiceEncode == *voiceDecode {
			os.Exit(2)
		}
		const maxVoiceInput = 64 * 1024 * 1024
		raw, err := io.ReadAll(io.LimitReader(os.Stdin, maxVoiceInput+1))
		if err != nil || len(raw) > maxVoiceInput {
			os.Exit(3)
		}
		var output []byte
		if *voiceEncode {
			output, err = encodeVoiceInput(raw, *voiceInputRate, *voiceInputChannels, *voiceInputFormat)
		} else {
			output, err = decodeIMAADPCM(raw)
		}
		if err != nil || writeAll(os.Stdout, output) != nil {
			os.Exit(4)
		}
		return
	}
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
	dispatcher := newCommandDispatcher(b)
	for scanner.Scan() {
		var cmd command
		if err := json.Unmarshal(scanner.Bytes(), &cmd); err != nil {
			continue
		}
		if cmd.Op == "stop" {
			dispatcher.close()
			b.close()
			return
		}
		dispatcher.dispatch(cmd)
	}
	dispatcher.close()
	b.close()
}

func newCommandDispatcher(b *bridge) *commandDispatcher {
	return &commandDispatcher{
		key:     b.commandKey,
		handle:  b.handleTimed,
		emit:    b.emit,
		workers: make(map[string]*contactWorker),
	}
}

func (d *commandDispatcher) dispatch(cmd command) {
	key := d.key(cmd)
	worker := d.workers[key]
	if worker == nil {
		worker = &contactWorker{}
		worker.ready = sync.NewCond(&worker.mu)
		d.workers[key] = worker
		d.wg.Add(1)
		go d.run(worker)
	}
	worker.enqueue(commandWork{command: cmd, enqueued: time.Now()})
}

func (worker *contactWorker) enqueue(work commandWork) {
	worker.mu.Lock()
	worker.queue = append(worker.queue, work)
	worker.ready.Signal()
	worker.mu.Unlock()
}

func (worker *contactWorker) next() (commandWork, bool) {
	worker.mu.Lock()
	defer worker.mu.Unlock()
	for len(worker.queue) == 0 && !worker.closed {
		worker.ready.Wait()
	}
	if len(worker.queue) == 0 {
		return commandWork{}, false
	}
	work := worker.queue[0]
	worker.queue[0] = commandWork{}
	worker.queue = worker.queue[1:]
	return work, true
}

func (worker *contactWorker) close() {
	worker.mu.Lock()
	worker.closed = true
	worker.ready.Broadcast()
	worker.mu.Unlock()
}

func (d *commandDispatcher) run(worker *contactWorker) {
	defer d.wg.Done()
	for {
		work, ok := worker.next()
		if !ok {
			return
		}
		started := time.Now()
		metrics, err := d.handle(work.command)
		metrics.QueueWaitUS = durationUS(started.Sub(work.enqueued))
		metrics.HandlerUS = durationUS(time.Since(started))
		if work.command.ID == "" {
			continue
		}
		out := response{ID: work.command.ID, OK: err == nil, Metrics: &metrics}
		if err != nil {
			out.Error = err.Error()
		}
		d.emit(out)
	}
}

func (d *commandDispatcher) close() {
	for _, worker := range d.workers {
		worker.close()
	}
	d.wg.Wait()
}

func (b *bridge) commandKey(cmd command) string {
	if cmd.Destination != "" {
		return "destination:" + cmd.Destination
	}
	if cmd.Stream != "" {
		b.streamsMu.Lock()
		stream := b.byToken[cmd.Stream]
		b.streamsMu.Unlock()
		if stream != nil {
			return "destination:" + stream.destination
		}
		return "stream:" + cmd.Stream
	}
	return "global"
}

func (b *bridge) handle(cmd command) error {
	_, err := b.handleTimed(cmd)
	return err
}

func (b *bridge) handleTimed(cmd command) (timingMetrics, error) {
	metrics := timingMetrics{}
	if cmd.Op != "send" && cmd.Op != "reply" && cmd.Op != "warm" && cmd.Op != "probe" {
		return metrics, errors.New("operazione non supportata")
	}
	payload, err := decodePayload(cmd.Payload)
	if cmd.Op == "reply" {
		if err != nil || cmd.Stream == "" {
			return metrics, errors.New("risposta non valida")
		}
		b.streamsMu.Lock()
		stream := b.byToken[cmd.Stream]
		b.streamsMu.Unlock()
		if stream == nil {
			return metrics, errors.New("stream non più disponibile")
		}
		if err := stream.writeFrame(payload); err != nil {
			b.drop(stream)
			return metrics, err
		}
		return metrics, nil
	}
	if cmd.Destination == "" {
		return metrics, errors.New("destination mancante")
	}
	if !validDestination(cmd.Destination) {
		return metrics, errors.New("destination I2P non valida")
	}
	if cmd.Op == "probe" {
		return b.probeStream(cmd.Destination)
	}
	if err != nil {
		return metrics, errors.New("payload non valido")
	}
	stream, streamMetrics, err := b.stream(cmd.Destination)
	metrics = streamMetrics
	if err != nil {
		return metrics, err
	}
	if cmd.Op == "warm" {
		return metrics, nil
	}
	if err := stream.writeFrame(payload); err == nil {
		return metrics, nil
	}
	b.drop(stream)
	stream, streamMetrics, err = b.stream(cmd.Destination)
	metrics = streamMetrics
	if err != nil {
		return metrics, err
	}
	return metrics, stream.writeFrame(payload)
}

func (b *bridge) stream(destination string) (*peerStream, timingMetrics, error) {
	metrics := timingMetrics{}
	b.streamsMu.Lock()
	if stream := b.outbound[destination]; stream != nil {
		b.streamsMu.Unlock()
		return stream, metrics, nil
	}
	b.streamsMu.Unlock()
	metrics.ColdStream = true
	conn, reader, handshakeUS, err := b.openSAMSocket()
	metrics.SAMHandshakeUS = handshakeUS
	if err != nil {
		return nil, metrics, err
	}
	// No status round-trip: the first frame written just after this command may
	// be bundled into the I2P Streaming SYN by connectDelay.
	connectStarted := time.Now()
	if err := writeLine(conn, fmt.Sprintf("STREAM CONNECT ID=%s DESTINATION=%s SILENT=true", b.session, destination)); err != nil {
		conn.Close()
		return nil, metrics, err
	}
	metrics.SAMConnectCommandUS = durationUS(time.Since(connectStarted))
	_ = conn.SetDeadline(time.Time{})
	stream := &peerStream{destination: destination, token: b.token("out"), conn: conn}
	b.streamsMu.Lock()
	if current := b.outbound[destination]; current != nil {
		b.streamsMu.Unlock()
		conn.Close()
		metrics.ColdStream = false
		return current, metrics, nil
	}
	b.outbound[destination] = stream
	b.byToken[stream.token] = stream
	b.streamsMu.Unlock()
	go b.readFrames(stream, reader)
	return stream, metrics, nil
}

func (b *bridge) openSAMSocket() (net.Conn, *bufio.Reader, int64, error) {
	started := time.Now()
	conn, err := net.DialTimeout("tcp", b.host, 15*time.Second)
	if err != nil {
		return nil, nil, durationUS(time.Since(started)), err
	}
	if tcp, ok := conn.(*net.TCPConn); ok {
		_ = tcp.SetNoDelay(true)
		_ = tcp.SetKeepAlive(true)
		_ = tcp.SetKeepAlivePeriod(30 * time.Second)
	}
	reader := bufio.NewReader(conn)
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
	if err := writeLine(conn, "HELLO VERSION MIN=3.1 MAX=3.3"); err != nil {
		conn.Close()
		return nil, nil, durationUS(time.Since(started)), err
	}
	line, err := reader.ReadString('\n')
	if err != nil || !strings.Contains(line, "RESULT=OK") {
		conn.Close()
		return nil, nil, durationUS(time.Since(started)), fmt.Errorf("handshake SAM fallito: %s", strings.TrimSpace(line))
	}
	return conn, reader, durationUS(time.Since(started)), nil
}

func (b *bridge) probeStream(destination string) (timingMetrics, error) {
	metrics := timingMetrics{ColdStream: true}
	conn, reader, handshakeUS, err := b.openSAMSocket()
	metrics.SAMHandshakeUS = handshakeUS
	if err != nil {
		return metrics, err
	}
	defer conn.Close()

	// SILENT=false is intentionally used only by this explicit measurement.
	// It provides the STREAM STATUS needed to measure real I2P stream opening,
	// while normal sends retain the lower-latency SILENT=true path.
	_ = conn.SetDeadline(time.Now().Add(75 * time.Second))
	started := time.Now()
	if err := writeLine(conn, fmt.Sprintf("STREAM CONNECT ID=%s DESTINATION=%s SILENT=false", b.session, destination)); err != nil {
		return metrics, err
	}
	line, err := reader.ReadString('\n')
	metrics.I2PStreamOpenUS = durationUS(time.Since(started))
	if err != nil {
		return metrics, err
	}
	if !strings.Contains(line, "RESULT=OK") {
		return metrics, fmt.Errorf("apertura stream I2P fallita: %s", strings.TrimSpace(line))
	}
	return metrics, nil
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
	_ = conn.SetDeadline(time.Now().Add(5 * time.Second))
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
	_ = conn.SetDeadline(time.Time{})
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

func durationUS(duration time.Duration) int64 {
	microseconds := duration.Microseconds()
	if duration > 0 && microseconds == 0 {
		return 1
	}
	return microseconds
}
