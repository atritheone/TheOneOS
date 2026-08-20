#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

#ifndef O_CLOEXEC
#define O_CLOEXEC 0
#endif
#ifndef O_NOFOLLOW
#define O_NOFOLLOW 0
#endif

#define MAX_CREDENTIAL_BYTES 4096
#define MAX_PASSWORD_BYTES 128
#define HASH_BYTES 32

extern int argon2id_hash_raw(uint32_t time_cost, uint32_t memory_cost,
		uint32_t parallelism, const void *password, size_t password_length,
		const void *salt, size_t salt_length, void *hash, size_t hash_length);

static int parse_number(const char *text, unsigned long minimum,
		unsigned long maximum, unsigned long *result)
{
	char *end = NULL;
	unsigned long value;

	if (!text || !*text)
		return -1;
	errno = 0;
	value = strtoul(text, &end, 10);
	if (errno || !end || *end || value < minimum || value > maximum)
		return -1;
	*result = value;
	return 0;
}

static int decode_hex(const char *text, unsigned char *output, size_t length)
{
	size_t index;

	if (!text || strlen(text) != length * 2)
		return -1;
	for (index = 0; index < length; index++) {
		unsigned char high = (unsigned char)text[index * 2];
		unsigned char low = (unsigned char)text[index * 2 + 1];
		unsigned int high_value, low_value;

		if (high >= '0' && high <= '9')
			high_value = high - '0';
		else if (high >= 'a' && high <= 'f')
			high_value = high - 'a' + 10;
		else if (high >= 'A' && high <= 'F')
			high_value = high - 'A' + 10;
		else
			return -1;
		if (low >= '0' && low <= '9')
			low_value = low - '0';
		else if (low >= 'a' && low <= 'f')
			low_value = low - 'a' + 10;
		else if (low >= 'A' && low <= 'F')
			low_value = low - 'A' + 10;
		else
			return -1;
		output[index] = (unsigned char)((high_value << 4) | low_value);
	}
	return 0;
}

static int decode_base64url(const char *text, unsigned char *output,
		size_t output_capacity, size_t *output_length)
{
	char encoded[192];
	size_t length, padding, index;
	int decoded;

	if (!text)
		return -1;
	length = strlen(text);
	if (!length || length > 170)
		return -1;
	padding = (4 - length % 4) % 4;
	if (length + padding >= sizeof(encoded))
		return -1;
	for (index = 0; index < length; index++) {
		unsigned char character = (unsigned char)text[index];
		if ((character >= 'A' && character <= 'Z') ||
				(character >= 'a' && character <= 'z') ||
				(character >= '0' && character <= '9')) {
			encoded[index] = (char)character;
		} else if (character == '-') {
			encoded[index] = '+';
		} else if (character == '_') {
			encoded[index] = '/';
		} else {
			return -1;
		}
	}
	while (padding)
		encoded[length + --padding] = '=';
	padding = (4 - length % 4) % 4;
	encoded[length + padding] = '\0';
	if (((length + padding) / 4) * 3 > output_capacity + padding)
		return -1;
	decoded = EVP_DecodeBlock(output, (const unsigned char *)encoded,
		(int)(length + padding));
	if (decoded < 0 || (size_t)decoded < padding)
		return -1;
	*output_length = (size_t)decoded - padding;
	return 0;
}

static int verify_current(const unsigned char *password, size_t password_length,
		const char *stored)
{
	char representation[1024];
	char *cursor, *parts[8];
	unsigned char salt[32], expected[HASH_BYTES], actual[HASH_BYTES];
	size_t salt_length = 0, expected_length = 0;
	unsigned long first, second, parallelism;
	int result = -1;
	int index;

	if (strlen(stored) >= sizeof(representation))
		return -1;
	strcpy(representation, stored);
	cursor = representation;
	for (index = 0; index < 8; index++) {
		parts[index] = strsep(&cursor, "$");
		if (!parts[index])
			goto out;
	}
	if (cursor || strcmp(parts[0], "t1auth") || strcmp(parts[1], "v=1"))
		goto out;
	if (decode_base64url(strchr(parts[6], '=') ? strchr(parts[6], '=') + 1 : NULL,
			salt, sizeof(salt), &salt_length) || salt_length < 16 ||
			decode_base64url(strchr(parts[7], '=') ? strchr(parts[7], '=') + 1 : NULL,
			expected, sizeof(expected), &expected_length) ||
			expected_length != HASH_BYTES)
		goto out;

	if (!strcmp(parts[2], "kdf=argon2id")) {
		if (strncmp(parts[3], "m=", 2) || strncmp(parts[4], "t=", 2) ||
				strncmp(parts[5], "p=", 2) || strncmp(parts[6], "salt=", 5) ||
				strncmp(parts[7], "hash=", 5) ||
				parse_number(parts[3] + 2, 32768, 262144, &first) ||
				parse_number(parts[4] + 2, 2, 6, &second) ||
				parse_number(parts[5] + 2, 1, 4, &parallelism))
			goto out;
		if (argon2id_hash_raw((uint32_t)second, (uint32_t)first,
				(uint32_t)parallelism, password, password_length, salt,
				salt_length, actual, sizeof(actual)) != 0)
			goto out;
	} else if (!strcmp(parts[2], "kdf=scrypt")) {
		if (strncmp(parts[3], "n=", 2) || strncmp(parts[4], "r=", 2) ||
				strncmp(parts[5], "p=", 2) || strncmp(parts[6], "salt=", 5) ||
				strncmp(parts[7], "hash=", 5) ||
				parse_number(parts[3] + 2, 16384, 65536, &first) ||
				(first & (first - 1)) ||
				parse_number(parts[4] + 2, 8, 8, &second) ||
				parse_number(parts[5] + 2, 1, 2, &parallelism))
			goto out;
		if (!EVP_PBE_scrypt((const char *)password, password_length, salt,
				salt_length, first, second, parallelism, 128U * 1024U * 1024U,
				actual, sizeof(actual)))
			goto out;
	} else {
		goto out;
	}
	result = CRYPTO_memcmp(actual, expected, sizeof(actual)) == 0 ? 0 : 1;
out:
	OPENSSL_cleanse(actual, sizeof(actual));
	OPENSSL_cleanse(expected, sizeof(expected));
	OPENSSL_cleanse(salt, sizeof(salt));
	OPENSSL_cleanse(representation, sizeof(representation));
	return result;
}

static int verify_legacy(const unsigned char *password, size_t password_length,
		const char *stored)
{
	char representation[256];
	char *cursor, *algorithm, *iterations, *salt_text, *hash_text;
	unsigned char salt[16], expected[HASH_BYTES], actual[HASH_BYTES];
	int result = -1;

	if (strlen(stored) != 111 || strlen(stored) >= sizeof(representation))
		return -1;
	strcpy(representation, stored);
	cursor = representation;
	algorithm = strsep(&cursor, "$");
	iterations = strsep(&cursor, "$");
	salt_text = strsep(&cursor, "$");
	hash_text = strsep(&cursor, "$");
	if (!algorithm || !iterations || !salt_text || !hash_text || cursor ||
			strcmp(algorithm, "sha256") || strcmp(iterations, "100000") ||
			decode_hex(salt_text, salt, sizeof(salt)) ||
			decode_hex(hash_text, expected, sizeof(expected)))
		goto out;
	if (!PKCS5_PBKDF2_HMAC((const char *)password, (int)password_length,
			salt, sizeof(salt), 100000, EVP_sha256(), sizeof(actual), actual))
		goto out;
	result = CRYPTO_memcmp(actual, expected, sizeof(actual)) == 0 ? 0 : 1;
out:
	OPENSSL_cleanse(actual, sizeof(actual));
	OPENSSL_cleanse(expected, sizeof(expected));
	OPENSSL_cleanse(salt, sizeof(salt));
	OPENSSL_cleanse(representation, sizeof(representation));
	return result;
}

static int safe_username(const char *username)
{
	size_t index, length = strlen(username);

	if (!length || length > 32)
		return 0;
	for (index = 0; index < length; index++) {
		unsigned char character = (unsigned char)username[index];
		if (!((character >= 'A' && character <= 'Z') ||
				(character >= 'a' && character <= 'z') ||
				(character >= '0' && character <= '9') || character == '.' ||
				character == '_' || character == '-'))
			return 0;
		if (index == 0 && !(character >= 'A' && character <= 'Z') &&
				!(character >= 'a' && character <= 'z') &&
				!(character >= '0' && character <= '9'))
			return 0;
	}
	return 1;
}

int main(int argc, char **argv)
{
	int descriptor = -1, status = 2;
	struct stat metadata;
	char credentials[MAX_CREDENTIAL_BYTES + 1];
	unsigned char password[MAX_PASSWORD_BYTES + 3];
	ssize_t count;
	char *newline, *separator, *stored;
	size_t credential_length = 0, password_length;

	if (argc != 2)
		return 2;
	descriptor = open(argv[1], O_RDONLY | O_CLOEXEC | O_NOFOLLOW);
	if (descriptor < 0 || fstat(descriptor, &metadata) ||
			!S_ISREG(metadata.st_mode) || metadata.st_uid != 0 ||
			(metadata.st_mode & 077) || metadata.st_nlink != 1 ||
			metadata.st_size <= 0 || metadata.st_size > MAX_CREDENTIAL_BYTES)
		goto out;
	while (credential_length < (size_t)metadata.st_size) {
		count = read(descriptor, credentials + credential_length,
				(size_t)metadata.st_size - credential_length);
		if (count < 0 && errno == EINTR)
			continue;
		if (count <= 0)
			goto out;
		credential_length += (size_t)count;
	}
	credentials[credential_length] = '\0';
	newline = strchr(credentials, '\n');
	if (newline) {
		if (newline[1] != '\0')
			goto out;
		*newline = '\0';
	}
	separator = strchr(credentials, ':');
	if (!separator)
		goto out;
	*separator = '\0';
	stored = separator + 1;
	if (!safe_username(credentials) || !*stored || strchr(stored, ':'))
		goto out;

	count = read(STDIN_FILENO, password, sizeof(password));
	if (count < 0 || count > MAX_PASSWORD_BYTES + 2)
		goto out;
	password_length = (size_t)count;
	if (password_length && password[password_length - 1] == '\n')
		password_length--;
	if (password_length && password[password_length - 1] == '\r')
		password_length--;
	if (password_length > MAX_PASSWORD_BYTES ||
			memchr(password, '\0', password_length))
		goto out;

	if (!strncmp(stored, "t1auth$", 7))
		status = verify_current(password, password_length, stored);
	else
		status = verify_legacy(password, password_length, stored);
	if (status < 0)
		status = 2;
out:
	if (descriptor >= 0)
		close(descriptor);
	OPENSSL_cleanse(password, sizeof(password));
	OPENSSL_cleanse(credentials, sizeof(credentials));
	return status;
}
