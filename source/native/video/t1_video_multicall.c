#include <string.h>

int t1_video_player_main(int argc, char **argv);
int t1_media_decode_worker_entry(int argc, char **argv);

/*
 * T1OS's measured hardware policy authorizes the exact executable path
 * /the one/software/audio/t1-video-decode.  Keep Player's established CLI as
 * the default entry and expose the sandboxed packet worker through an explicit
 * internal mode in the same compiled executable.  The worker entry independently
 * refuses execution unless uid/gid, parent-death, dumpability and no_new_privs
 * invariants established by t1-media-decoderd all verify.
 */
int
main(int argc, char **argv)
{
    for (int index = 1; index < argc; ++index) {
        if (!strcmp(argv[index], "--t1md-worker"))
            return t1_media_decode_worker_entry(argc, argv);
    }
    return t1_video_player_main(argc, argv);
}
