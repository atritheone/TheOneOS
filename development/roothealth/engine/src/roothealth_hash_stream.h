#ifndef ROOTHEALTH_HASH_STREAM_H
#define ROOTHEALTH_HASH_STREAM_H

#include <stddef.h>
#include <stdint.h>

struct rh_hash_stream {
	uint32_t state[8];
	uint64_t bits;
	unsigned char block[64];
	size_t used;
	int failed;
};

void rh_hash_stream_init(struct rh_hash_stream *stream);
int rh_hash_stream_update(struct rh_hash_stream *stream, const void *data,
		size_t length);
int rh_hash_stream_final(struct rh_hash_stream *stream,
		unsigned char output[32]);

#endif
