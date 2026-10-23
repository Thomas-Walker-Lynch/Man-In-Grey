/*
  Man_In_Grey_file_gate

  The gate of the bespoke journal interpreter for the file command language.
  Installed setuid root, it starts the journal interpreter with root's rights
  while the real uid still names the caller. Unblessed, it starts the journal
  interpreter with the caller's rights.

  The journal interpreter is at a path fixed when the gate is compiled,
  relative to the gate: ../Man_In_Grey/journal_interpreter_file.py. The caller
  cannot name another. When running privileged, the gate refuses to start it
  unless the interpreter, and every directory above it, is owned by root and
  writable by no other account.

  The journal arrives on standard input and is passed on unread. Every
  argument is passed on to the journal interpreter, except --print-flags,
  which reports the caller and whether the gate is running privileged.

  Who is allowed to hand a journal to the interpreter is decided by the
  interpreter's constraints, not here.
*/

#include <errno.h>
#include <libgen.h>
#include <limits.h>
#include <pwd.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

#define PYTHON "/usr/bin/python3"
#define INTERPRETER_RELATIVE "../Man_In_Grey/journal_interpreter_file.py"
#define ARGUMENT_MAX 64

Local void die(const char *format ,...){
  va_list ap; va_start(ap ,format);
  fputs("Man_In_Grey_file_gate: " ,stderr);
  vfprintf(stderr ,format ,ap); va_end(ap);
  fputc('\n' ,stderr);
  _exit(2);
}

Local bool privileged(void){
  return geteuid() != getuid() || getegid() != getgid();
}

/* path and every directory above it: owned by root, writable by no other account */
Local void check_owned_by_root(const char *path){
  char prefix[PATH_MAX];
  size_t length = strlen(path);
  if(length >= sizeof prefix) die("path too long: %s" ,path);
  for(size_t i = 1; i <= length; ++i){
    if( i < length && path[i] != '/' ) continue;
    memcpy(prefix ,path ,i); prefix[i] = '\0';
    struct stat st;
    if( lstat(prefix ,&st) != 0 ) die("cannot examine %s: %s" ,prefix ,strerror(errno));
    if( st.st_uid != 0 ) die("refusing to run privileged: %s is not owned by root" ,prefix);
    if( st.st_mode & (S_IWGRP | S_IWOTH) ) die("refusing to run privileged: %s is writable by an account other than root" ,prefix);
  }
  struct stat st;
  if( lstat("/" ,&st) != 0 || st.st_uid != 0 ) die("refusing to run privileged: / is not owned by root");
}

Local void print_flags(void){
  struct passwd *pw = getpwuid(getuid());
  printf("caller.uid=%ld\n" ,(long)getuid());
  printf("caller.name=%s\n" ,pw ? pw->pw_name : "unknown");
  printf("effective.uid=%ld\n" ,(long)geteuid());
  printf("privileged=%d\n" ,privileged() ? 1 : 0);
}

int main(int argc ,char **argv){
  if( argc > 1 && strcmp(argv[1] ,"--print-flags") == 0 ){ print_flags(); return 0; }
  if( argc > ARGUMENT_MAX ) die("too many arguments");

  char exe[PATH_MAX];
  ssize_t n = readlink("/proc/self/exe" ,exe ,sizeof exe - 1);
  if( n < 0 ) die("cannot resolve /proc/self/exe: %s" ,strerror(errno));
  exe[n] = '\0';

  char candidate[PATH_MAX];
  if( snprintf(candidate ,sizeof candidate ,"%s/%s" ,dirname(exe) ,INTERPRETER_RELATIVE) >= (int)sizeof candidate )
    die("path too long");
  char interpreter[PATH_MAX];
  if( !realpath(candidate ,interpreter) ) die("journal interpreter not found: %s" ,candidate);

  if( privileged() ) check_owned_by_root(interpreter);

  /* harden the process before starting the interpreter */
  uid_t caller_uid = getuid();
  gid_t caller_gid = getgid();
  struct passwd *pw = getpwuid(caller_uid);
  char caller_name[256];
  snprintf(caller_name ,sizeof caller_name ,"%s" ,pw ? pw->pw_name : "unknown");

  clearenv();
  setenv("PATH" ,"/usr/sbin:/usr/bin:/sbin:/bin" ,1);
  setenv("LANG" ,"C.UTF-8" ,1);
  umask(077);
  prctl(PR_SET_DUMPABLE ,0 ,0 ,0 ,0);
  if( chdir("/") != 0 ) die("cannot change directory to /");

  char number[32];
  snprintf(number ,sizeof number ,"%ld" ,(long)caller_uid); setenv("MIG_CALLER_UID" ,number ,1);
  snprintf(number ,sizeof number ,"%ld" ,(long)caller_gid); setenv("MIG_CALLER_GID" ,number ,1);
  setenv("MIG_CALLER_NAME" ,caller_name ,1);

  /* python3 -E -s -B <interpreter> <arguments> */
  char *argument[ARGUMENT_MAX + 6];
  int k = 0;
  argument[k++] = (char *)PYTHON;
  argument[k++] = (char *)"-E";
  argument[k++] = (char *)"-s";
  argument[k++] = (char *)"-B";
  argument[k++] = interpreter;
  for(int i = 1; i < argc; ++i) argument[k++] = argv[i];
  argument[k] = NULL;

  execv(PYTHON ,argument);
  die("cannot start %s: %s" ,PYTHON ,strerror(errno));
}
