#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

/*
 * Linux shebang parsing cannot represent the space in `/the one`.  This tiny
 * launcher preserves the familiar executable command experience and hands the
 * invoked command name to the audited Python dispatcher.
 */
int
main(int argc, char **argv)
{
    static const char python[] = "/the one/software/python/bin/python";
    static const char dispatcher[] = "/the one/build/python/pythonentry.py";
    char **arguments;
    int index;

    if (argc < 1 || argv == NULL || argv[0] == NULL) {
        return 126;
    }
    arguments = calloc((size_t)argc + 5, sizeof(*arguments));
    if (arguments == NULL) {
        fputs("T1OS Python command: out of memory\n", stderr);
        return 126;
    }
    arguments[0] = (char *)python;
    arguments[1] = "-B";
    arguments[2] = "-P";
    arguments[3] = (char *)dispatcher;
    arguments[4] = argv[0];
    for (index = 1; index < argc; ++index) {
        arguments[index + 4] = argv[index];
    }
    arguments[argc + 4] = NULL;
    execv(python, arguments);
    fprintf(stderr, "T1OS Python command: %s: %s\n", python, strerror(errno));
    free(arguments);
    return 126;
}
