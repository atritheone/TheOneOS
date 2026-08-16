#include "config.h"

#include <stdio.h>
#include <string.h>

#include "roothealth_hash_stream.h"
#include "roothealth_write.h"

int main(void)
{
	static const unsigned char expected[32] = {
		0xba, 0x78, 0x16, 0xbf, 0x8f, 0x01, 0xcf, 0xea,
		0x41, 0x41, 0x40, 0xde, 0x5d, 0xae, 0x22, 0x23,
		0xb0, 0x03, 0x61, 0xa3, 0x96, 0x17, 0x7a, 0x9c,
		0xb4, 0x10, 0xff, 0x61, 0xf2, 0x00, 0x15, 0xad,
	};
	struct rh_hash_stream stream;
	unsigned char streamed[32], one_shot[32];

	rh_hash_stream_init(&stream);
	if (rh_hash_stream_update(&stream, "a", 1) ||
			rh_hash_stream_update(&stream, "bc", 2) ||
			rh_hash_stream_final(&stream, streamed))
		return 1;
	rh_sha256("abc", 3, one_shot);
	if (memcmp(streamed, expected, sizeof(expected)) ||
			memcmp(streamed, one_shot, sizeof(streamed)))
		return 1;
	printf("sha256-stream chunks=2 known-vector=abc one-shot-compatible=1\n");
	return 0;
}
