package main

import (
	"bytes"
	"encoding/base64"
	"io"
	"net"
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
