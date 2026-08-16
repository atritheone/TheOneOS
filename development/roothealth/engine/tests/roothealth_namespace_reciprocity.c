/* ROOTHEALTH_REPAIR_ROLE(DIAGNOSTIC) */
#include "config.h"

#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_namespace.h"
#include "roothealth_write.h"

static int digest(const unsigned char *value, size_t length,
		unsigned char output[32])
{
	return rh_namespace_file_name_reciprocity_hash(value, length, output);
}

int main(void)
{
	static const char name[] = "sample";
	unsigned char value[offsetof(FILE_NAME_ATTR, file_name) +
		(sizeof(name) - 1U) * 2U];
	unsigned char changed[sizeof(value)], baseline[32], candidate[32];
	FILE_NAME_ATTR *file_name = (FILE_NAME_ATTR *)value;
	size_t i;
	unsigned int ignored = 0, stable = 0;

	memset(value, 0, sizeof(value));
	file_name->parent_directory = MK_LE_MREF(5U, 7U);
	for (i = offsetof(FILE_NAME_ATTR, creation_time);
			i < offsetof(FILE_NAME_ATTR, file_name_length); i++)
		value[i] = (unsigned char)(0x40U + i);
	file_name->file_name_length = sizeof(name) - 1U;
	file_name->file_name_type = FILE_NAME_POSIX;
	for (i = 0; i < sizeof(name) - 1U; i++)
		file_name->file_name[i] = cpu_to_le16((uint16_t)(unsigned char)name[i]);
	if (digest(value, sizeof(value), baseline))
		return 1;

	/* Every documented cached-only byte may differ without changing the
	 * semantic reciprocity digest.  The complete raw values are separately
	 * hashed by the namespace manifests. */
	for (i = offsetof(FILE_NAME_ATTR, creation_time);
			i < offsetof(FILE_NAME_ATTR, file_name_length); i++) {
		memcpy(changed, value, sizeof(changed));
		changed[i] ^= 0x5aU;
		if (digest(changed, sizeof(changed), candidate) ||
				memcmp(candidate, baseline, sizeof(candidate)) ||
				!memcmp(changed, value, sizeof(changed)))
			return 1;
		ignored++;
	}

	for (i = 0; i < offsetof(FILE_NAME_ATTR, creation_time); i++) {
		memcpy(changed, value, sizeof(changed));
		changed[i] ^= 1U;
		if (digest(changed, sizeof(changed), candidate) ||
				!memcmp(candidate, baseline, sizeof(candidate)))
			return 1;
		stable++;
	}
	memcpy(changed, value, sizeof(changed));
	changed[offsetof(FILE_NAME_ATTR, file_name_type)] = FILE_NAME_WIN32;
	if (digest(changed, sizeof(changed), candidate) ||
			!memcmp(candidate, baseline, sizeof(candidate)))
		return 1;
	stable++;
	for (i = offsetof(FILE_NAME_ATTR, file_name); i < sizeof(value); i++) {
		memcpy(changed, value, sizeof(changed));
		changed[i] ^= 1U;
		if (digest(changed, sizeof(changed), candidate) ||
				!memcmp(candidate, baseline, sizeof(candidate)))
			return 1;
		stable++;
	}
	memcpy(changed, value, sizeof(changed));
	changed[offsetof(FILE_NAME_ATTR, file_name_length)]--;
	if (!digest(changed, sizeof(changed), candidate))
		return 1;
	stable++;
	if (!digest(value, sizeof(value) - 1U, candidate))
		return 1;

	printf("namespace-reciprocity cached-bytes-ignored=%u "
		"stable-mutations-refused=%u full-values-manifest-bound=1 writes=0\n",
		ignored, stable);
	return 0;
}
