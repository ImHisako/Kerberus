package main

import (
	"bufio"
	"bytes"
	"encoding/base64"
	"io"
	"net"
	"strconv"
	"strings"
	"sync"
	"testing"
	"time"
)

type shortWriter struct {
	buffer bytes.Buffer
}

func (w *shortWriter) Write(data []byte) (int, error) {
	if len(data) > 2 {
		data = data[:2]
	}
	return w.buffer.Write(data)
}

func TestWriteAllHandlesShortWrites(t *testing.T) {
	w := &shortWriter{}
	if err := writeAll(w, []byte("abcdef")); err != nil {
		t.Fatal(err)
	}
	if got := w.buffer.String(); got != "abcdef" {
		t.Fatalf("got %q", got)
	}
}

func TestDestinationRejectsCommandInjection(t *testing.T) {
	if validDestination("peer\nSTREAM ACCEPT ID=other") {
		t.Fatal("destination containing newline was accepted")
	}
	if !validDestination("example.b32.i2p") {
		t.Fatal("valid b32 destination was rejected")
	}
}

func TestWriteAllRejectsZeroProgress(t *testing.T) {
	err := writeAll(zeroWriter{}, []byte("x"))
	if err != io.ErrShortWrite {
		t.Fatalf("got %v", err)
	}
}

type zeroWriter struct{}

func (zeroWriter) Write([]byte) (int, error) { return 0, nil }

func TestReplyUsesTheExactInboundStream(t *testing.T) {
	local, remote := net.Pipe()
	defer local.Close()
	defer remote.Close()
	b := &bridge{
		outbound: make(map[string]*peerStream),
		byToken:  make(map[string]*peerStream),
		stop:     make(chan struct{}),
	}
	stream := &peerStream{destination: "peer", token: "in-1", inbound: true, conn: local}
	b.byToken[stream.token] = stream
	payload := []byte("ack")
	done := make(chan error, 1)
	go func() {
		done <- b.handle(command{
			Op:      "reply",
			Stream:  "in-1",
			Payload: base64.StdEncoding.EncodeToString(payload),
		})
	}()
	_ = remote.SetReadDeadline(time.Now().Add(time.Second))
	header := make([]byte, 4)
	if _, err := io.ReadFull(remote, header); err != nil {
		t.Fatal(err)
	}
	received := make([]byte, len(payload))
	if _, err := io.ReadFull(remote, received); err != nil {
		t.Fatal(err)
	}
	if err := <-done; err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(received, payload) {
		t.Fatalf("got %q", received)
	}
}

func TestInboundStreamIsReusedForReverseMessages(t *testing.T) {
	b := &bridge{
		outbound: make(map[string]*peerStream),
		byToken:  make(map[string]*peerStream),
	}
	stream := &peerStream{destination: "peer-destination", token: "in-7", inbound: true}
	b.registerInbound(stream)
	if b.outbound[stream.destination] != stream {
		t.Fatal("accepted full-duplex stream was not made available for replies")
	}
	if b.byToken[stream.token] != stream {
		t.Fatal("accepted stream token was not registered")
	}
}

func TestDispatcherRunsDifferentContactsConcurrently(t *testing.T) {
	slowStarted := make(chan struct{})
	releaseSlow := make(chan struct{})
	fastDone := make(chan struct{})
	var slowOnce sync.Once
	dispatcher := &commandDispatcher{
		key: func(cmd command) string { return cmd.Destination },
		handle: func(cmd command) (timingMetrics, error) {
			if cmd.Destination == "slow" {
				slowOnce.Do(func() {
					close(slowStarted)
					<-releaseSlow
				})
			} else {
				close(fastDone)
			}
			return timingMetrics{}, nil
		},
		emit:    func(response) {},
		workers: make(map[string]*contactWorker),
	}
	dispatcher.dispatch(command{Op: "warm", Destination: "slow"})
	<-slowStarted
	for range 1_000 {
		dispatcher.dispatch(command{Op: "warm", Destination: "slow"})
	}
	dispatcher.dispatch(command{Op: "warm", Destination: "fast"})
	select {
	case <-fastDone:
	case <-time.After(time.Second):
		t.Fatal("a slow contact blocked a different contact")
	}
	close(releaseSlow)
	dispatcher.close()
}

func TestDispatcherPreservesOrderForOneContact(t *testing.T) {
	firstStarted := make(chan struct{})
	releaseFirst := make(chan struct{})
	secondStarted := make(chan struct{})
	var once sync.Once
	dispatcher := &commandDispatcher{
		key: func(cmd command) string { return cmd.Destination },
		handle: func(cmd command) (timingMetrics, error) {
			if cmd.ID == "first" {
				once.Do(func() { close(firstStarted) })
				<-releaseFirst
			} else {
				close(secondStarted)
			}
			return timingMetrics{}, nil
		},
		emit:    func(response) {},
		workers: make(map[string]*contactWorker),
	}
	dispatcher.dispatch(command{ID: "first", Op: "warm", Destination: "same"})
	<-firstStarted
	dispatcher.dispatch(command{ID: "second", Op: "warm", Destination: "same"})
	select {
	case <-secondStarted:
		t.Fatal("second command overtook the first command for the same contact")
	case <-time.After(50 * time.Millisecond):
	}
	close(releaseFirst)
	select {
	case <-secondStarted:
	case <-time.After(time.Second):
		t.Fatal("second command was not processed after the first")
	}
	dispatcher.close()
}

func TestProbeSeparatesLocalHandshakeAndI2PStreamOpen(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	serverDone := make(chan error, 1)
	go func() {
		conn, err := listener.Accept()
		if err != nil {
			serverDone <- err
			return
		}
		defer conn.Close()
		reader := bufio.NewReader(conn)
		hello, err := reader.ReadString('\n')
		if err != nil {
			serverDone <- err
			return
		}
		if !strings.HasPrefix(hello, "HELLO VERSION") {
			serverDone <- io.ErrUnexpectedEOF
			return
		}
		if _, err := conn.Write([]byte("HELLO REPLY RESULT=OK VERSION=3.3\n")); err != nil {
			serverDone <- err
			return
		}
		connect, err := reader.ReadString('\n')
		if err != nil {
			serverDone <- err
			return
		}
		if !strings.Contains(connect, "STREAM CONNECT") || !strings.Contains(connect, "SILENT=false") {
			serverDone <- io.ErrUnexpectedEOF
			return
		}
		time.Sleep(time.Millisecond)
		_, err = conn.Write([]byte("STREAM STATUS RESULT=OK\n"))
		serverDone <- err
	}()

	bridge := &bridge{host: listener.Addr().String(), session: "test-session"}
	metrics, err := bridge.probeStream("peer-destination")
	if err != nil {
		t.Fatal(err)
	}
	if metrics.SAMHandshakeUS <= 0 {
		t.Fatal("local SAM handshake was not measured")
	}
	if metrics.I2PStreamOpenUS < 1_000 {
		t.Fatalf("I2P stream status wait was not measured: %d us", metrics.I2PStreamOpenUS)
	}
	if err := <-serverDone; err != nil {
		t.Fatal(err)
	}
}

func BenchmarkDispatcherDifferentContacts(b *testing.B) {
	dispatcher := &commandDispatcher{
		key:     func(cmd command) string { return cmd.Destination },
		handle:  func(command) (timingMetrics, error) { return timingMetrics{}, nil },
		emit:    func(response) {},
		workers: make(map[string]*contactWorker),
	}
	b.ResetTimer()
	for index := 0; index < b.N; index++ {
		dispatcher.dispatch(command{Op: "warm", Destination: "peer-" + strconv.Itoa(index%32)})
	}
	dispatcher.close()
}

func BenchmarkWriteFrame(b *testing.B) {
	stream := &peerStream{conn: discardConn{}}
	payload := bytes.Repeat([]byte("x"), 1024)
	b.SetBytes(int64(len(payload)))
	b.ResetTimer()
	for range b.N {
		if err := stream.writeFrame(payload); err != nil {
			b.Fatal(err)
		}
	}
}

type discardConn struct{}

func (discardConn) Read([]byte) (int, error)         { return 0, io.EOF }
func (discardConn) Write(value []byte) (int, error)  { return len(value), nil }
func (discardConn) Close() error                     { return nil }
func (discardConn) LocalAddr() net.Addr              { return nil }
func (discardConn) RemoteAddr() net.Addr             { return nil }
func (discardConn) SetDeadline(time.Time) error      { return nil }
func (discardConn) SetReadDeadline(time.Time) error  { return nil }
func (discardConn) SetWriteDeadline(time.Time) error { return nil }
