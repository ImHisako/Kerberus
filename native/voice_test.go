package main

import (
	"encoding/binary"
	"math"
	"testing"
)

func TestVoiceCodecRoundTripAndHeader(t *testing.T) {
	pcm := make([]byte, voiceSampleRate*2)
	for index := 0; index < voiceSampleRate; index++ {
		value := int16(math.Sin(2*math.Pi*440*float64(index)/voiceSampleRate) * 12000)
		binary.LittleEndian.PutUint16(pcm[index*2:], uint16(value))
	}
	encoded, err := encodeVoiceInput(pcm, voiceSampleRate, 1, "s16le")
	if err != nil {
		t.Fatal(err)
	}
	if string(encoded[:4]) != "KVA1" || len(encoded) >= len(pcm)/2+32 {
		t.Fatalf("unexpected encoded voice: magic=%q bytes=%d", encoded[:4], len(encoded))
	}
	decoded, err := decodeIMAADPCM(encoded)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded) != len(pcm) {
		t.Fatalf("decoded %d bytes, want %d", len(decoded), len(pcm))
	}
	var squared float64
	for index := 0; index < voiceSampleRate; index++ {
		want := int16(binary.LittleEndian.Uint16(pcm[index*2:]))
		got := int16(binary.LittleEndian.Uint16(decoded[index*2:]))
		difference := float64(int(want) - int(got))
		squared += difference * difference
	}
	rmse := math.Sqrt(squared / voiceSampleRate)
	if rmse > 1800 {
		t.Fatalf("ADPCM RMSE too high: %.1f", rmse)
	}
}

func TestVoiceCodecDownmixesAndResamplesFloatPCM(t *testing.T) {
	frames := 48_000
	raw := make([]byte, frames*2*4)
	for index := 0; index < frames; index++ {
		binary.LittleEndian.PutUint32(raw[(index*2)*4:], math.Float32bits(0.25))
		binary.LittleEndian.PutUint32(raw[(index*2+1)*4:], math.Float32bits(-0.25))
	}
	encoded, err := encodeVoiceInput(raw, 48_000, 2, "f32le")
	if err != nil {
		t.Fatal(err)
	}
	decoded, err := decodeIMAADPCM(encoded)
	if err != nil {
		t.Fatal(err)
	}
	if len(decoded) != voiceSampleRate*2 {
		t.Fatalf("resampled length=%d", len(decoded))
	}
}

func TestVoiceDecoderRejectsMalformedAndOversizedContainers(t *testing.T) {
	if _, err := decodeIMAADPCM([]byte("not voice")); err == nil {
		t.Fatal("malformed voice was accepted")
	}
	encoded := make([]byte, voiceHeaderSize)
	copy(encoded, []byte("KVA1"))
	binary.BigEndian.PutUint32(encoded[4:8], voiceSampleRate)
	binary.BigEndian.PutUint32(encoded[8:12], voiceMaxSamples+1)
	if _, err := decodeIMAADPCM(encoded); err == nil {
		t.Fatal("oversized voice was accepted")
	}
}

func BenchmarkVoiceEncode20Seconds(b *testing.B) {
	pcm := make([]byte, voiceSampleRate*2*20)
	b.SetBytes(int64(len(pcm)))
	b.ResetTimer()
	for range b.N {
		if _, err := encodeVoiceInput(pcm, voiceSampleRate, 1, "s16le"); err != nil {
			b.Fatal(err)
		}
	}
}

func BenchmarkVoiceDecode20Seconds(b *testing.B) {
	encoded, err := encodeVoiceInput(make([]byte, voiceSampleRate*2*20), voiceSampleRate, 1, "s16le")
	if err != nil {
		b.Fatal(err)
	}
	b.SetBytes(int64(voiceSampleRate * 2 * 20))
	b.ResetTimer()
	for range b.N {
		if _, err := decodeIMAADPCM(encoded); err != nil {
			b.Fatal(err)
		}
	}
}
