package main

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"math"
)

const (
	voiceSampleRate = 16_000
	voiceMaxSeconds = 120
	voiceMaxSamples = voiceSampleRate * voiceMaxSeconds
	voiceHeaderSize = 16
)

var imaIndexTable = [...]int{-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8}

var imaStepTable = [...]int{
	7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31,
	34, 37, 41, 45, 50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143,
	157, 173, 190, 209, 230, 253, 279, 307, 337, 371, 408, 449, 494, 544,
	598, 658, 724, 796, 876, 963, 1060, 1166, 1282, 1411, 1552, 1707, 1878,
	2066, 2272, 2499, 2749, 3024, 3327, 3660, 4026, 4428, 4871, 5358, 5894,
	6484, 7132, 7845, 8630, 9493, 10442, 11487, 12635, 13899, 15289, 16818,
	18500, 20350, 22385, 24623, 27086, 29794, 32767,
}

func encodeVoiceInput(raw []byte, sampleRate, channels int, sampleFormat string) ([]byte, error) {
	samples, err := normalizeVoicePCM(raw, sampleRate, channels, sampleFormat)
	if err != nil {
		return nil, err
	}
	return encodeIMAADPCM(samples)
}

func normalizeVoicePCM(raw []byte, sampleRate, channels int, sampleFormat string) ([]int16, error) {
	if sampleRate < 8_000 || sampleRate > 192_000 || channels < 1 || channels > 8 {
		return nil, errors.New("formato audio non supportato")
	}
	bytesPerSample := map[string]int{"u8": 1, "s16le": 2, "s32le": 4, "f32le": 4}[sampleFormat]
	if bytesPerSample == 0 {
		return nil, errors.New("formato campione non supportato")
	}
	frameSize := bytesPerSample * channels
	if len(raw) == 0 || len(raw)%frameSize != 0 {
		return nil, errors.New("PCM non valido")
	}
	frames := len(raw) / frameSize
	if frames > sampleRate*voiceMaxSeconds {
		return nil, errors.New("messaggio vocale oltre 120 secondi")
	}
	mono := make([]float64, frames)
	for frame := 0; frame < frames; frame++ {
		var mixed float64
		for channel := 0; channel < channels; channel++ {
			offset := (frame*channels + channel) * bytesPerSample
			switch sampleFormat {
			case "u8":
				mixed += float64(int(raw[offset])-128) / 128.0
			case "s16le":
				mixed += float64(int16(binary.LittleEndian.Uint16(raw[offset:]))) / 32768.0
			case "s32le":
				mixed += float64(int32(binary.LittleEndian.Uint32(raw[offset:]))) / 2147483648.0
			case "f32le":
				value := float64(math.Float32frombits(binary.LittleEndian.Uint32(raw[offset:])))
				if math.IsNaN(value) || math.IsInf(value, 0) {
					value = 0
				}
				mixed += value
			}
		}
		mono[frame] = math.Max(-1, math.Min(1, mixed/float64(channels)))
	}
	outCount := int(math.Round(float64(frames) * voiceSampleRate / float64(sampleRate)))
	if outCount < 1 || outCount > voiceMaxSamples {
		return nil, errors.New("durata audio non valida")
	}
	result := make([]int16, outCount)
	for index := range result {
		position := float64(index) * float64(sampleRate) / voiceSampleRate
		left := int(position)
		if left >= len(mono)-1 {
			left = len(mono) - 1
			result[index] = floatToInt16(mono[left])
			continue
		}
		fraction := position - float64(left)
		result[index] = floatToInt16(mono[left]*(1-fraction) + mono[left+1]*fraction)
	}
	return result, nil
}

func floatToInt16(value float64) int16 {
	value = math.Max(-1, math.Min(1, value))
	if value <= -1 {
		return -32768
	}
	return int16(math.Round(value * 32767))
}

func encodeIMAADPCM(samples []int16) ([]byte, error) {
	if len(samples) < 1 || len(samples) > voiceMaxSamples {
		return nil, errors.New("numero campioni non valido")
	}
	predictor := int(samples[0])
	index := 0
	payload := make([]byte, (len(samples)-1+1)/2)
	for sampleIndex := 1; sampleIndex < len(samples); sampleIndex++ {
		code := imaEncodeNibble(int(samples[sampleIndex]), &predictor, &index)
		position := sampleIndex - 1
		if position%2 == 0 {
			payload[position/2] = code
		} else {
			payload[position/2] |= code << 4
		}
	}
	result := make([]byte, voiceHeaderSize+len(payload))
	copy(result, []byte("KVA1"))
	binary.BigEndian.PutUint32(result[4:8], voiceSampleRate)
	binary.BigEndian.PutUint32(result[8:12], uint32(len(samples)))
	binary.BigEndian.PutUint16(result[12:14], uint16(samples[0]))
	result[14] = 0
	result[15] = 0
	copy(result[voiceHeaderSize:], payload)
	return result, nil
}

func decodeIMAADPCM(encoded []byte) ([]byte, error) {
	if len(encoded) < voiceHeaderSize || !bytes.Equal(encoded[:4], []byte("KVA1")) {
		return nil, errors.New("contenitore vocale non valido")
	}
	if binary.BigEndian.Uint32(encoded[4:8]) != voiceSampleRate {
		return nil, errors.New("frequenza vocale non supportata")
	}
	count := int(binary.BigEndian.Uint32(encoded[8:12]))
	if count < 1 || count > voiceMaxSamples {
		return nil, errors.New("numero campioni non valido")
	}
	expected := voiceHeaderSize + (count-1+1)/2
	if len(encoded) != expected || encoded[15] != 0 || encoded[14] > 88 {
		return nil, errors.New("dimensione vocale non valida")
	}
	predictor := int(int16(binary.BigEndian.Uint16(encoded[12:14])))
	index := int(encoded[14])
	pcm := make([]byte, count*2)
	binary.LittleEndian.PutUint16(pcm[:2], uint16(int16(predictor)))
	for sampleIndex := 1; sampleIndex < count; sampleIndex++ {
		position := sampleIndex - 1
		packed := encoded[voiceHeaderSize+position/2]
		code := packed & 0x0f
		if position%2 == 1 {
			code = packed >> 4
		}
		value := imaDecodeNibble(code, &predictor, &index)
		binary.LittleEndian.PutUint16(pcm[sampleIndex*2:], uint16(int16(value)))
	}
	return pcm, nil
}

func imaEncodeNibble(sample int, predictor *int, index *int) byte {
	step := imaStepTable[*index]
	difference := sample - *predictor
	code := byte(0)
	if difference < 0 {
		code = 8
		difference = -difference
	}
	delta := step >> 3
	if difference >= step {
		code |= 4
		difference -= step
		delta += step
	}
	if difference >= step>>1 {
		code |= 2
		difference -= step >> 1
		delta += step >> 1
	}
	if difference >= step>>2 {
		code |= 1
		delta += step >> 2
	}
	if code&8 != 0 {
		*predictor -= delta
	} else {
		*predictor += delta
	}
	*predictor = max(-32768, min(32767, *predictor))
	*index = max(0, min(88, *index+imaIndexTable[code]))
	return code
}

func imaDecodeNibble(code byte, predictor *int, index *int) int {
	if code > 15 {
		panic(fmt.Sprintf("invalid IMA nibble %d", code))
	}
	step := imaStepTable[*index]
	delta := step >> 3
	if code&4 != 0 {
		delta += step
	}
	if code&2 != 0 {
		delta += step >> 1
	}
	if code&1 != 0 {
		delta += step >> 2
	}
	if code&8 != 0 {
		*predictor -= delta
	} else {
		*predictor += delta
	}
	*predictor = max(-32768, min(32767, *predictor))
	*index = max(0, min(88, *index+imaIndexTable[code]))
	return *predictor
}
