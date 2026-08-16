/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <errno.h>
#include <stdint.h>
#include <string.h>

#include "roothealth_hash_stream.h"

static uint32_t rh_rotr32(uint32_t value, unsigned int count)
{
	return (value >> count) | (value << (32U - count));
}

static void rh_transform(struct rh_hash_stream *stream,
		const unsigned char block[64])
{
	static const uint32_t k[64] = {
		0x428a2f98U, 0x71374491U, 0xb5c0fbcfU, 0xe9b5dba5U,
		0x3956c25bU, 0x59f111f1U, 0x923f82a4U, 0xab1c5ed5U,
		0xd807aa98U, 0x12835b01U, 0x243185beU, 0x550c7dc3U,
		0x72be5d74U, 0x80deb1feU, 0x9bdc06a7U, 0xc19bf174U,
		0xe49b69c1U, 0xefbe4786U, 0x0fc19dc6U, 0x240ca1ccU,
		0x2de92c6fU, 0x4a7484aaU, 0x5cb0a9dcU, 0x76f988daU,
		0x983e5152U, 0xa831c66dU, 0xb00327c8U, 0xbf597fc7U,
		0xc6e00bf3U, 0xd5a79147U, 0x06ca6351U, 0x14292967U,
		0x27b70a85U, 0x2e1b2138U, 0x4d2c6dfcU, 0x53380d13U,
		0x650a7354U, 0x766a0abbU, 0x81c2c92eU, 0x92722c85U,
		0xa2bfe8a1U, 0xa81a664bU, 0xc24b8b70U, 0xc76c51a3U,
		0xd192e819U, 0xd6990624U, 0xf40e3585U, 0x106aa070U,
		0x19a4c116U, 0x1e376c08U, 0x2748774cU, 0x34b0bcb5U,
		0x391c0cb3U, 0x4ed8aa4aU, 0x5b9cca4fU, 0x682e6ff3U,
		0x748f82eeU, 0x78a5636fU, 0x84c87814U, 0x8cc70208U,
		0x90befffaU, 0xa4506cebU, 0xbef9a3f7U, 0xc67178f2U
	};
	uint32_t words[64];
	uint32_t a, b, c, d, e, f, g, h;
	unsigned int i;

	for (i = 0; i < 16U; i++)
		words[i] = ((uint32_t)block[4U * i] << 24) |
			((uint32_t)block[4U * i + 1U] << 16) |
			((uint32_t)block[4U * i + 2U] << 8) |
			(uint32_t)block[4U * i + 3U];
	for (i = 16U; i < 64U; i++) {
		uint32_t s0 = rh_rotr32(words[i - 15U], 7U) ^
			rh_rotr32(words[i - 15U], 18U) ^ (words[i - 15U] >> 3);
		uint32_t s1 = rh_rotr32(words[i - 2U], 17U) ^
			rh_rotr32(words[i - 2U], 19U) ^ (words[i - 2U] >> 10);

		words[i] = words[i - 16U] + s0 + words[i - 7U] + s1;
	}
	a = stream->state[0]; b = stream->state[1]; c = stream->state[2];
	d = stream->state[3]; e = stream->state[4]; f = stream->state[5];
	g = stream->state[6]; h = stream->state[7];
	for (i = 0; i < 64U; i++) {
		uint32_t s1 = rh_rotr32(e, 6U) ^ rh_rotr32(e, 11U) ^
			rh_rotr32(e, 25U);
		uint32_t choose = (e & f) ^ ((~e) & g);
		uint32_t first = h + s1 + choose + k[i] + words[i];
		uint32_t s0 = rh_rotr32(a, 2U) ^ rh_rotr32(a, 13U) ^
			rh_rotr32(a, 22U);
		uint32_t majority = (a & b) ^ (a & c) ^ (b & c);
		uint32_t second = s0 + majority;

		h = g; g = f; f = e; e = d + first;
		d = c; c = b; b = a; a = first + second;
	}
	stream->state[0] += a; stream->state[1] += b;
	stream->state[2] += c; stream->state[3] += d;
	stream->state[4] += e; stream->state[5] += f;
	stream->state[6] += g; stream->state[7] += h;
}

void rh_hash_stream_init(struct rh_hash_stream *stream)
{
	static const uint32_t initial[8] = {
		0x6a09e667U, 0xbb67ae85U, 0x3c6ef372U, 0xa54ff53aU,
		0x510e527fU, 0x9b05688cU, 0x1f83d9abU, 0x5be0cd19U
	};

	memset(stream, 0, sizeof(*stream));
	memcpy(stream->state, initial, sizeof(initial));
}

int rh_hash_stream_update(struct rh_hash_stream *stream, const void *data,
		size_t length)
{
	const unsigned char *input = data;

	if (!stream || (!data && length) || stream->failed ||
			length > (UINT64_MAX - stream->bits) / 8U) {
		if (stream)
			stream->failed = 1;
		errno = EOVERFLOW;
		return -1;
	}
	stream->bits += (uint64_t)length * 8U;
	while (length) {
		size_t take = sizeof(stream->block) - stream->used;

		if (take > length)
			take = length;
		memcpy(stream->block + stream->used, input, take);
		stream->used += take;
		input += take;
		length -= take;
		if (stream->used == sizeof(stream->block)) {
			rh_transform(stream, stream->block);
			stream->used = 0;
		}
	}
	return 0;
}

int rh_hash_stream_final(struct rh_hash_stream *stream,
		unsigned char output[32])
{
	uint64_t bits;
	unsigned int i;

	if (!stream || !output || stream->failed) {
		errno = EINVAL;
		return -1;
	}
	bits = stream->bits;
	stream->block[stream->used++] = 0x80;
	if (stream->used > 56U) {
		memset(stream->block + stream->used, 0,
			sizeof(stream->block) - stream->used);
		rh_transform(stream, stream->block);
		stream->used = 0;
	}
	memset(stream->block + stream->used, 0, 56U - stream->used);
	for (i = 0; i < 8U; i++)
		stream->block[63U - i] = (unsigned char)(bits >> (8U * i));
	rh_transform(stream, stream->block);
	for (i = 0; i < 8U; i++) {
		output[4U * i] = (unsigned char)(stream->state[i] >> 24);
		output[4U * i + 1U] = (unsigned char)(stream->state[i] >> 16);
		output[4U * i + 2U] = (unsigned char)(stream->state[i] >> 8);
		output[4U * i + 3U] = (unsigned char)stream->state[i];
	}
	stream->failed = 1;
	return 0;
}
