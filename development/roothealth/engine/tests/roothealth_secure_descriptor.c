#include "config.h"

#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "endians.h"
#include "layout.h"
#include "roothealth_secure.h"

#define RH_SYSTEM_ACCESS_FILTER_ACE_TYPE 0x15U
#define RH_TRUST_PROTECTED_FILTER_ACE_FLAG 0x40U

static size_t put_sid(unsigned char *bytes)
{
	SID *sid = (SID *)bytes;

	memset(bytes, 0, 12);
	sid->revision = SID_REVISION;
	sid->sub_authority_count = 1;
	sid->identifier_authority.value[5] = 5;
	sid->sub_authority[0] = cpu_to_le32(32);
	return 12;
}

static size_t make_descriptor(unsigned char *bytes, unsigned int ace_type,
		uint32_t object_flags, size_t application_length)
{
	SECURITY_DESCRIPTOR_RELATIVE *descriptor =
		(SECURITY_DESCRIPTOR_RELATIVE *)bytes;
	ACL *acl;
	ACE_HEADER *ace;
	unsigned char *cursor;
	size_t ace_length, descriptor_length;

	memset(bytes, 0, 256);
	descriptor->revision = SECURITY_DESCRIPTOR_REVISION;
	descriptor->control = cpu_to_le16(SE_SELF_RELATIVE | SE_DACL_PRESENT);
	descriptor->owner = cpu_to_le32(20);
	put_sid(bytes + 20);
	descriptor->dacl = cpu_to_le32(32);
	acl = (ACL *)(bytes + 32);
	acl->revision = ace_type >= ACCESS_ALLOWED_OBJECT_ACE_TYPE ?
		ACL_REVISION_DS : ace_type == ACCESS_ALLOWED_COMPOUND_ACE_TYPE ?
		ACL_REVISION3 : ACL_REVISION;
	acl->ace_count = cpu_to_le16(1);
	ace = (ACE_HEADER *)(bytes + 40);
	ace->type = (ACE_TYPES)ace_type;
	cursor = bytes + 48;
	if (ace_type == ACCESS_ALLOWED_COMPOUND_ACE_TYPE) {
		cursor[0] = 1;
		cursor[1] = cursor[2] = cursor[3] = 0;
		cursor += 4;
	} else if ((ace_type >= ACCESS_ALLOWED_OBJECT_ACE_TYPE &&
			ace_type <= SYSTEM_ALARM_OBJECT_ACE_TYPE) ||
			ace_type == ACCESS_ALLOWED_CALLBACK_OBJECT_ACE_TYPE ||
			ace_type == ACCESS_DENIED_CALLBACK_OBJECT_ACE_TYPE ||
			ace_type == SYSTEM_AUDIT_CALLBACK_OBJECT_ACE_TYPE ||
			ace_type == SYSTEM_ALARM_CALLBACK_OBJECT_ACE_TYPE) {
		cursor[0] = (unsigned char)object_flags;
		cursor[1] = (unsigned char)(object_flags >> 8);
		cursor[2] = (unsigned char)(object_flags >> 16);
		cursor[3] = (unsigned char)(object_flags >> 24);
		cursor += 4;
		if (object_flags & 1U) {
			memset(cursor, 0x11, 16);
			cursor += 16;
		}
		if (object_flags & 2U) {
			memset(cursor, 0x22, 16);
			cursor += 16;
		}
	}
	cursor += put_sid(cursor);
	memset(cursor, 0x6b, application_length);
	cursor += application_length;
	ace_length = (size_t)(cursor - (unsigned char *)ace);
	ace->size = cpu_to_le16((uint16_t)ace_length);
	acl->size = cpu_to_le16((uint16_t)(8U + ace_length));
	descriptor_length = 32U + 8U + ace_length;
	return descriptor_length;
}

static size_t make_resource_descriptor(unsigned char *bytes,
		uint16_t value_type)
{
	SECURITY_DESCRIPTOR_RELATIVE *descriptor =
		(SECURITY_DESCRIPTOR_RELATIVE *)bytes;
	ACL *acl;
	ACE_HEADER *ace;
	unsigned char *claim;
	size_t claim_length;
	const unsigned char everyone[12] = {
		1, 1, 0, 0, 0, 0, 0, 1, 0, 0, 0, 0
	};

	memset(bytes, 0, 256);
	descriptor->revision = SECURITY_DESCRIPTOR_REVISION;
	descriptor->control = cpu_to_le16(SE_SELF_RELATIVE | SE_SACL_PRESENT);
	descriptor->owner = cpu_to_le32(20);
	put_sid(bytes + 20);
	descriptor->sacl = cpu_to_le32(32);
	acl = (ACL *)(bytes + 32);
	acl->revision = ACL_REVISION_DS;
	acl->ace_count = cpu_to_le16(1);
	ace = (ACE_HEADER *)(bytes + 40);
	ace->type = SYSTEM_RESOURCE_ATTRIBUTE_ACE_TYPE;
	memcpy(bytes + 48, everyone, sizeof(everyone));
	claim = bytes + 60;
	claim[0] = 20; /* Name offset. */
	claim[4] = (unsigned char)value_type;
	claim[5] = (unsigned char)(value_type >> 8);
	claim[12] = 1; /* ValueCount. */
	claim[16] = 24; /* First value offset. */
	claim[20] = 'A';
	claim[21] = claim[22] = claim[23] = 0;
	if (value_type == 1U || value_type == 2U || value_type == 6U) {
		claim[24] = value_type == 6U ? 1U : 0x2aU;
		claim_length = 32U;
	} else if (value_type == 3U) {
		claim[24] = 'B';
		claim[25] = claim[26] = claim[27] = 0;
		claim_length = 28U;
	} else if (value_type == 5U) {
		claim[24] = sizeof(everyone);
		memcpy(claim + 28U, everyone, sizeof(everyone));
		claim_length = 40U;
	} else {
		claim[24] = 3U;
		claim[28] = 0xdeU;
		claim[29] = 0xadU;
		claim[30] = 0xbeU;
		claim_length = 32U;
	}
	ace->size = cpu_to_le16((uint16_t)(20U + claim_length));
	acl->size = cpu_to_le16((uint16_t)(28U + claim_length));
	return 60U + claim_length;
}

static size_t make_filter_descriptor(unsigned char *bytes, unsigned int flags,
		int trust_sid, int system_acl)
{
	SECURITY_DESCRIPTOR_RELATIVE *descriptor =
		(SECURITY_DESCRIPTOR_RELATIVE *)bytes;
	ACL *acl;
	ACE_HEADER *ace;
	SID *sid;
	size_t sid_length, ace_length;

	memset(bytes, 0, 256);
	descriptor->revision = SECURITY_DESCRIPTOR_REVISION;
	descriptor->control = cpu_to_le16(SE_SELF_RELATIVE |
		(system_acl ? SE_SACL_PRESENT : SE_DACL_PRESENT));
	descriptor->owner = cpu_to_le32(20);
	put_sid(bytes + 20);
	if (system_acl)
		descriptor->sacl = cpu_to_le32(32);
	else
		descriptor->dacl = cpu_to_le32(32);
	acl = (ACL *)(bytes + 32);
	acl->revision = ACL_REVISION_DS;
	acl->ace_count = cpu_to_le16(1);
	ace = (ACE_HEADER *)(bytes + 40);
	ace->type = (ACE_TYPES)RH_SYSTEM_ACCESS_FILTER_ACE_TYPE;
	ace->flags = (ACE_FLAGS)flags;
	sid = (SID *)(bytes + 48);
	if (trust_sid) {
		sid->revision = SID_REVISION;
		sid->sub_authority_count = 2;
		sid->identifier_authority.value[5] = 19;
		sid->sub_authority[0] = cpu_to_le32(0x200U);
		sid->sub_authority[1] = cpu_to_le32(0x1000U);
		sid_length = 16U;
	} else
		sid_length = put_sid((unsigned char *)sid);
	/* Filter condition is receive-side opaque, bounded ACE data. */
	memcpy((unsigned char *)sid + sid_length, "FILT", 4U);
	ace_length = 8U + sid_length + 4U;
	ace->size = cpu_to_le16((uint16_t)ace_length);
	acl->size = cpu_to_le16((uint16_t)(8U + ace_length));
	return 40U + ace_length;
}

static void move_acl_to_sacl(unsigned char *bytes)
{
	SECURITY_DESCRIPTOR_RELATIVE *descriptor =
		(SECURITY_DESCRIPTOR_RELATIVE *)bytes;

	descriptor->control = cpu_to_le16(SE_SELF_RELATIVE | SE_SACL_PRESENT);
	descriptor->sacl = cpu_to_le32(32);
	descriptor->dacl = 0;
}

static int expect(int condition, const char *name)
{
	if (condition)
		return 0;
	fprintf(stderr, "descriptor case failed: %s\n", name);
	return -1;
}

int main(void)
{
	unsigned char descriptor[256], mutated[256];
	size_t length;
	size_t cases = 0;

	if (expect(!rh_secure_test_ranges_overlap(UINT64_MAX - 3U, 2U,
			UINT64_MAX - 1U, 1U), "near-U64 disjoint ranges") ||
			expect(rh_secure_test_ranges_overlap(UINT64_MAX - 3U, 4U,
				UINT64_MAX - 1U, 1U), "near-U64 overlapping ranges") ||
			expect(!rh_secure_test_ranges_overlap(UINT64_MAX - 1U, 4U,
				0U, 1U), "overflowing range cannot wrap to zero"))
		return 1;
	cases += 3U;

	length = make_descriptor(descriptor, ACCESS_ALLOWED_ACE_TYPE, 0, 0);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"standard ACE"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((ACE_HEADER *)(mutated + 40))->size = cpu_to_le16(16);
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"short ACE body"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->group = cpu_to_le32(24);
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"partial component overlap"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->group = cpu_to_le32(20);
	if (expect(rh_secure_descriptor_bytes_valid(mutated, length),
			"exact shared owner/group SID"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->control |= cpu_to_le16(0x40);
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"reserved descriptor control"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->alignment = 0x5a;
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->control |=
		cpu_to_le16(SE_RM_CONTROL_VALID);
	if (expect(rh_secure_descriptor_bytes_valid(mutated, length),
			"RM control byte"))
		return 1;
	cases++;
	((SECURITY_DESCRIPTOR_RELATIVE *)mutated)->control &=
		cpu_to_le16((uint16_t)~SE_RM_CONTROL_VALID);
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"RM byte without control flag"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[21] = SID_MAX_SUB_AUTHORITIES + 1;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"oversized SID"))
		return 1;
	cases++;
	length = make_descriptor(descriptor, ACCESS_ALLOWED_OBJECT_ACE_TYPE,
		3U, 0);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"object ACE with both GUIDs"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((ACL *)(mutated + 32))->revision = ACL_REVISION;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"object ACE requires DS ACL revision"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[48] = 4U;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"unknown object ACE flags"))
		return 1;
	cases++;
	length = make_descriptor(descriptor, ACCESS_ALLOWED_CALLBACK_ACE_TYPE,
		0, 4);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"bounded callback application data"))
		return 1;
	cases++;
	length = make_descriptor(descriptor, ACCESS_ALLOWED_COMPOUND_ACE_TYPE,
		0, 0);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"compound impersonation ACE"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[48] = 2;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"undefined compound type"))
		return 1;
	cases++;
	length = make_resource_descriptor(descriptor, 6U);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"resource boolean claim graph"))
		return 1;
	cases++;
	for (uint16_t type = 1U; type <= 0x10U; type++) {
		if (type != 1U && type != 2U && type != 3U && type != 5U &&
				type != 6U && type != 0x10U)
			continue;
		length = make_resource_descriptor(descriptor, type);
		if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
				"supported resource claim value type"))
			return 1;
		cases++;
	}
	length = make_resource_descriptor(descriptor, 6U);
	memcpy(mutated, descriptor, length);
	mutated[66] = 0xa5; /* Reserved is ignored on receive. */
	mutated[67] = 0x5a;
	mutated[70] = 0x34; /* Upper 16 flag bits are application-defined. */
	mutated[71] = 0x12;
	if (expect(rh_secure_descriptor_bytes_valid(mutated, length),
			"resource receive-side reserved and application flags"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[68] = 0x40; /* Lower flag bits 6..15 are not defined. */
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"resource undefined lower flag"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[76] = 21; /* Misaligned value offset. */
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"claim value offset"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[84] = 2; /* BOOLEAN must be zero or one. */
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"claim boolean domain"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[44] = 1; /* Resource ACE mask must be zero. */
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"resource ACE mask"))
		return 1;
	cases++;
	length = make_descriptor(descriptor, SYSTEM_MANDATORY_LABEL_ACE_TYPE,
		0, 0);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"mandatory label is SACL-only"))
		return 1;
	cases++;
	move_acl_to_sacl(descriptor);
	descriptor[44] = 1; /* NO_WRITE_UP. */
	memset(descriptor + 50, 0, 6);
	descriptor[55] = 16; /* SECURITY_MANDATORY_LABEL_AUTHORITY. */
	descriptor[56] = 0;
	descriptor[57] = 0x20; /* Medium RID 0x2000. */
	descriptor[58] = descriptor[59] = 0;
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"mandatory SACL mask and label SID"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[44] = 8;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"mandatory mask domain"))
		return 1;
	cases++;
	length = make_descriptor(descriptor, SYSTEM_SCOPED_POLICY_ID_ACE_TYPE,
		0, 0);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"scoped policy is SACL-only"))
		return 1;
	cases++;
	move_acl_to_sacl(descriptor);
	memset(descriptor + 50, 0, 6);
	descriptor[55] = 17; /* SECURITY_SCOPED_POLICY_ID_AUTHORITY. */
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"scoped policy SACL"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[44] = 1;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"scoped policy mask must be zero"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	mutated[55] = 5;
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"scoped policy SID authority"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0, 1, 1);
	((ACE_HEADER *)(descriptor + 40))->type =
		SYSTEM_PROCESS_TRUST_LABEL_ACE_TYPE;
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"process trust label SID"))
		return 1;
	cases++;
	memcpy(mutated, descriptor, length);
	((SID *)(mutated + 48))->sub_authority[0] = cpu_to_le32(0x300U);
	if (expect(!rh_secure_descriptor_bytes_valid(mutated, length),
			"process trust protection type domain"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0, 1, 0);
	((ACE_HEADER *)(descriptor + 40))->type =
		SYSTEM_PROCESS_TRUST_LABEL_ACE_TYPE;
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"process trust label is SACL-only"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0, 0, 1);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"access filter SACL with opaque condition"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor,
		RH_TRUST_PROTECTED_FILTER_ACE_FLAG, 1, 1);
	if (expect(rh_secure_descriptor_bytes_valid(descriptor, length),
			"trust-protected access filter"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0, 0, 0);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"access filter is SACL-only"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0, 0, 1);
	((ACL *)(descriptor + 32))->revision = ACL_REVISION;
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"access filter requires DS ACL revision"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor,
		RH_TRUST_PROTECTED_FILTER_ACE_FLAG, 0, 1);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"trust-protected filter requires TrustLevelSid"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor,
		RH_TRUST_PROTECTED_FILTER_ACE_FLAG, 1, 1);
	((SID *)(descriptor + 48))->sub_authority[0] = cpu_to_le32(0x300U);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"TrustLevelSid protection type domain"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor,
		RH_TRUST_PROTECTED_FILTER_ACE_FLAG, 1, 1);
	((SID *)(descriptor + 48))->sub_authority[1] = cpu_to_le32(0x700U);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"TrustLevelSid protection level domain"))
		return 1;
	cases++;
	length = make_filter_descriptor(descriptor, 0x80U, 0, 1);
	if (expect(!rh_secure_descriptor_bytes_valid(descriptor, length),
			"access filter rejects audit-failure flag"))
		return 1;
	cases++;
	printf("descriptor_cases=%zu resource_attribute=validated\n", cases);
	return 0;
}
