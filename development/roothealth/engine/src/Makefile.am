if REALLYSTATIC
AM_LIBS		= $(top_builddir)/libntfs/.libs/libntfs.a $(NTFSPROGS_STATIC_LIBS)
# older builds may need -static instead of newer -all-static
AM_LFLAGS	= -static
STATIC_LINK     = $(CC) $(AM_CFLAGS) $(CFLAGS) $(LDFLAGS) -o $@
else
AM_LIBS		= $(top_builddir)/libntfs/libntfs.la
AM_LFLAGS	= $(all_libraries)
LIBTOOL_LINK    = $(LIBTOOL) --mode=link $(CCLD) $(AM_CFLAGS) $(CFLAGS) $(LDFLAGS) -o $@
endif

# Workaround to make REALLYSTATIC work with automake 1.5.
LINK=$(STATIC_LINK) $(LIBTOOL_LINK)

bin_PROGRAMS		= ntfsinfo ntfscluster ntfsls ntfscat ntfscmp
sbin_PROGRAMS		= mkntfs ntfslabel ntfsclone ntfsck ntfsresize \
			  ntfsundelete ntfscp roothealth

# Built only with --enable-extras (and ntfsmove also needs --enable-quarantined),
# matching upstream ntfsprogs classification.
EXTRA_PROGRAM_NAMES	= ntfswipe
QUARANTINED_PROGRAM_NAMES = ntfsmove

CLEANFILES		= $(EXTRA_PROGRAMS)

if ENABLE_EXTRAS
bin_PROGRAMS		+= $(EXTRA_PROGRAM_NAMES)
if ENABLE_QUARANTINED
bin_PROGRAMS		+= $(QUARANTINED_PROGRAM_NAMES)
endif
else
EXTRA_PROGRAMS		= $(EXTRA_PROGRAM_NAMES) $(QUARANTINED_PROGRAM_NAMES)
endif

MAINTAINERCLEANFILES = Makefile.in

# Set the include path.
AM_CPPFLAGS		= -I$(top_srcdir)/include $(all_includes)

mkntfs_CPPFLAGS		= $(AM_CPPFLAGS) $(MKNTFS_CPPFLAGS)
mkntfs_SOURCES		= attrdef.c attrdef.h sd.c sd.h mkntfs.c utils.c utils.h
mkntfs_LDADD		= $(AM_LIBS) $(MKNTFS_LIBS) $(BLKID_LIBS)
mkntfs_LDFLAGS		= $(AM_LFLAGS)

ntfslabel_SOURCES	= ntfslabel.c utils.c utils.h
ntfslabel_LDADD		= $(AM_LIBS)
ntfslabel_LDFLAGS	= $(AM_LFLAGS)

ntfsinfo_SOURCES	= ntfsinfo.c utils.c utils.h
ntfsinfo_LDADD		= $(AM_LIBS)
ntfsinfo_LDFLAGS	= $(AM_LFLAGS)

ntfsresize_SOURCES	= ntfsresize.c utils.c utils.h
ntfsresize_LDADD	= $(AM_LIBS)
ntfsresize_LDFLAGS	= $(AM_LFLAGS)

ntfsclone_SOURCES	= ntfsclone.c utils.c utils.h
ntfsclone_LDADD		= $(AM_LIBS)
ntfsclone_LDFLAGS	= $(AM_LFLAGS)

ntfscluster_SOURCES	= ntfscluster.c ntfscluster.h cluster.c cluster.h utils.c utils.h
ntfscluster_LDADD	= $(AM_LIBS)
ntfscluster_LDFLAGS	= $(AM_LFLAGS)

ntfsck_SOURCES		= ntfsck.c utils.c utils.h
ntfsck_LDADD		= $(AM_LIBS)
ntfsck_LDFLAGS		= $(AM_LFLAGS)

roothealth_SOURCES = roothealth_repair_main.c \
	roothealth_orchestrator.c roothealth_orchestrator.h \
	roothealth_format3.c roothealth_format3.h \
	roothealth_report.c roothealth_report.h \
	roothealth_repair.c roothealth_repair.h \
	roothealth_write.c roothealth_write.h \
	roothealth_wal.c roothealth_wal.h \
	roothealth_recover.c roothealth_recover.h roothealth_playlog.c \
	roothealth_replay_guard.c roothealth_replay_guard.h \
	roothealth_replay_analysis.c roothealth_replay_analysis.h \
	roothealth_replay_analysis_internal.h \
	roothealth_native_authority.c roothealth_native_authority.h \
	roothealth_free_slot_authority.c roothealth_free_slot_authority.h \
	roothealth_free_slot_authority_internal.h \
	roothealth_census_device.c roothealth_census_device.h \
	roothealth_complete_census.c roothealth_complete_census.h \
	roothealth_coverage.c roothealth_coverage.h \
	roothealth_raw_mft.c roothealth_raw_mft.h roothealth_raw_mft_apply.c \
	roothealth_raw_mft_apply.h \
	roothealth_namespace.c roothealth_namespace.h \
	roothealth_namespace_repair.c roothealth_namespace_repair.h \
	roothealth_recovery_namespace_authority.c \
	roothealth_recovery_namespace_authority.h \
	roothealth_recovery_namespace_authority_internal.h \
	roothealth_system_indexes.c roothealth_system_indexes.h \
	roothealth_system_indexes_internal.h \
	roothealth_usn_fixed_system_authority.c \
	roothealth_usn_fixed_system_authority.h \
	roothealth_usn_fixed_system_authority_internal.h \
	roothealth_fixed_metadata_reader.c roothealth_fixed_metadata_reader.h \
	roothealth_compressed.c roothealth_compressed.h \
	roothealth_compressed_internal.h \
	attrdef.c attrdef.h \
	roothealth_secure.c roothealth_secure.h \
	roothealth_secure_raw.c roothealth_secure_raw.h \
	roothealth_secure_reader.h \
	roothealth_secure_index.c roothealth_secure_index.h \
	roothealth_secure_overlay.c roothealth_secure_overlay.h \
	roothealth_secure_census_provider.c \
	roothealth_secure_census_provider.h \
	roothealth_bitmap.c roothealth_bitmap.h roothealth_bitmap_apply.c \
	roothealth_mft_bitmap.c roothealth_mft_bitmap.h \
	roothealth_mft_bitmap_apply.c \
	roothealth_index_bitmap.c roothealth_index_bitmap.h \
	roothealth_index_bitmap_apply.c \
	roothealth_overlay.c roothealth_overlay.h \
	roothealth_dirty.c roothealth_dirty.h \
	roothealth_policy.c roothealth_policy.h roothealth_policy_internal.h \
	roothealth_hash_stream.c roothealth_hash_stream.h \
	utils.c utils.h
roothealth_LDADD = $(AM_LIBS)
roothealth_LDFLAGS = $(AM_LFLAGS)

ntfsls_SOURCES		= ntfsls.c utils.c utils.h list.h
ntfsls_LDADD		= $(AM_LIBS)
ntfsls_LDFLAGS		= $(AM_LFLAGS)

ntfscat_SOURCES		= ntfscat.c ntfscat.h utils.c utils.h
ntfscat_LDADD		= $(AM_LIBS)
ntfscat_LDFLAGS		= $(AM_LFLAGS)

ntfscmp_SOURCES		= ntfscmp.c utils.c utils.h
ntfscmp_LDADD		= $(AM_LIBS)
ntfscmp_LDFLAGS		= $(AM_LFLAGS)

ntfsundelete_SOURCES	= ntfsundelete.c ntfsundelete.h utils.c utils.h list.h
ntfsundelete_LDADD	= $(AM_LIBS)
ntfsundelete_LDFLAGS	= $(AM_LFLAGS)

ntfscp_SOURCES		= ntfscp.c utils.c utils.h
ntfscp_LDADD		= $(AM_LIBS)
ntfscp_LDFLAGS		= $(AM_LFLAGS)

ntfswipe_SOURCES	= ntfswipe.c ntfswipe.h utils.c utils.h
ntfswipe_LDADD		= $(AM_LIBS)
ntfswipe_LDFLAGS	= $(AM_LFLAGS)

ntfsmove_SOURCES	= ntfsmove.c ntfsmove.h utils.c utils.h
ntfsmove_LDADD		= $(AM_LIBS)
ntfsmove_LDFLAGS	= $(AM_LFLAGS)

# Extra targets

strip:	$(bin_PROGRAMS) $(sbin_PROGRAMS)
	$(STRIP) $^

libs:
	(cd ../libntfs && $(MAKE) libs) || exit 1;

extras:	libs $(EXTRA_PROGRAMS)

# mkfs.ntfs and fsck.ntfs symbolic links

install-exec-hook:
	$(INSTALL) -d $(DESTDIR)/$(sbindir)
	$(LN_S) -f $(sbindir)/mkntfs $(DESTDIR)$(sbindir)/mkfs.ntfs
	$(LN_S) -f $(sbindir)/ntfsck $(DESTDIR)$(sbindir)/fsck.ntfs

uninstall-local:
	$(RM) -f $(DESTDIR)/sbin/mkfs.ntfs
	$(RM) -f $(DESTDIR)/sbin/fsck.ntfs
