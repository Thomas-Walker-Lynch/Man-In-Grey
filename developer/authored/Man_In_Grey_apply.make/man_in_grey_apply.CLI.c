#define _GNU_SOURCE
#include <errno.h>
#include <grp.h>
#include <libgen.h>
#include <pwd.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

static void die(const char *fmt ,...) {
  va_list ap; va_start(ap ,fmt);
  vfprintf(stderr ,fmt ,ap); va_end(ap);
  fputc('\n' ,stderr);
  _exit(2);
}

static void sanitize_env(void) {
  clearenv();
  setenv("PATH" ,"/usr/sbin:/usr/bin:/sbin:/bin" ,1);
  setenv("LANG" ,"C.UTF-8" ,1);
}

static bool in_group(const char *group_name) {
  if (!group_name || !*group_name) return false;
  struct group *gr = getgrnam(group_name);
  if (!gr) return false;

  uid_t ruid = getuid();
  struct passwd *pw = getpwuid(ruid);
  if (!pw) return false;

  int ng = 0;
  getgrouplist(pw->pw_name ,getgid() ,NULL ,&ng);
  if (ng <= 0) return false;

  gid_t *ids = malloc((size_t)ng * sizeof(gid_t));
  if (!ids) return false;

  if (getgrouplist(pw->pw_name ,getgid() ,ids ,&ng) < 0) { free(ids); return false; }

  bool ok = false;
  for (int i = 0; i < ng; ++i) {
    if (ids[i] == gr->gr_gid) { ok = true; break; }
  }
  free(ids);
  return ok;
}

static char *exe_dirname(void) {
  static char buf[4096];
  ssize_t n = readlink("/proc/self/exe" ,buf ,sizeof(buf)-1);
  if (n < 0) die("cannot resolve /proc/self/exe: %s" ,strerror(errno));
  buf[n] = '\0';
  char *copy = strdup(buf);
  if (!copy) die("oom");
  char *dir = dirname(copy);
  return dir; /* caller frees */
}

static void print_flags(bool privileged ,bool in_sudo ,uid_t ruid) {
  struct passwd *pw = getpwuid(ruid);
  const char *name = pw ? pw->pw_name : "unknown";
  printf("caller.uid=%ld\n" ,(long)ruid);
  printf("caller.name=%s\n" ,name);
  printf("flag.this_process_privileged=%d\n" ,privileged ? 1 : 0);
  printf("flag.uid_in_group_sudo=%d\n" ,in_sudo ? 1 : 0);
}

int main(int argc ,char **argv) {
  /* defaults */
  const char *python = "/usr/bin/python3";
  char *bindir = exe_dirname();
  char inner_default[4096];
  snprintf(inner_default ,sizeof inner_default ,"%s/../python3/executor_inner.py" ,bindir);
  free(bindir);
  const char *inner = inner_default;

  /* minimal arg parse: --inner, --plan, --print-flags */
  char **forward = calloc((size_t)argc + 1 ,sizeof(char*));
  if (!forward) die("oom");
  int fi = 0;

  const char *plan_arg = NULL;
  bool plan_is_stdin = false;
  bool want_print_flags = false;

  for (int i = 1; i < argc; ++i) {
    if (strcmp(argv[i] ,"--inner") == 0 && i+1 < argc) { inner = argv[++i]; continue; }
    if (strcmp(argv[i] ,"--plan") == 0 && i+1 < argc) {
      plan_arg = argv[++i];
      plan_is_stdin = (strcmp(plan_arg ,"-") == 0);
      forward[fi++] = (char*)"--plan";
      forward[fi++] = (char*)plan_arg;
      continue;
    }
    if (strcmp(argv[i] ,"--print-flags") == 0) { want_print_flags = true; continue; }
    /* pass through any phase-2-* etc. */
    forward[fi++] = argv[i];
  }
  forward[fi] = NULL;

  /* compute flags */
  bool privileged = (geteuid() == 0);
  bool in_sudo = in_group("sudo"); /* /etc/group is world-readable */

  /* test option */
  if (want_print_flags) {
    print_flags(privileged ,in_sudo ,getuid());
    return 0;
  }

  /* policy: if privileged but real user is neither root nor in sudo, abort */
  uid_t ruid = getuid();
  if (privileged && ruid != 0 && !in_sudo) {
    struct passwd *pw = getpwuid(ruid);
    const char *name = pw ? pw->pw_name : "unknown";
    fprintf(stderr,
      "refusing privileged apply: real user '%s' is not root and not in group 'sudo'\n",
      name
    );
    return 1;
  }

  /* harden & annotate environment */
  sanitize_env();
  umask(077);
  prctl(PR_SET_DUMPABLE ,0 ,0 ,0 ,0);
  chdir("/");

  {
    char uidb[32] ,gidb[32];
    snprintf(uidb ,sizeof uidb ,"%ld" ,(long)getuid());
    snprintf(gidb ,sizeof gidb ,"%ld" ,(long)getgid());
    struct passwd *pw = getpwuid(getuid());
    setenv("MIG_CALLER_UID" ,uidb ,1);
    setenv("MIG_CALLER_GID" ,gidb ,1);
    setenv("MIG_CALLER_NAME" ,pw ? pw->pw_name : "unknown" ,1);
    setenv("MIG_FLAG_THIS_PROCESS_PRIVILEGED" ,privileged ? "1" : "0" ,1);
    setenv("MIG_FLAG_UID_IN_GROUP_SUDO" ,in_sudo ? "1" : "0" ,1);
  }

  /* build argv for inner */
  char *argv3[1024];
  size_t k = 0;
  argv3[k++] = (char*)python;
  argv3[k++] = (char*)inner;

  if (plan_is_stdin) {
    if (dup2(STDIN_FILENO ,3) < 0) die("dup2(stdin→3) failed: %s" ,strerror(errno));
    argv3[k++] = (char*)"--plan-fd";
    argv3[k++] = (char*)"3";
    /* strip the original --plan - from forward list */
    for (int i = 0; forward[i]; ++i) {
      if (strcmp(forward[i] ,"--plan") == 0 && forward[i+1] && strcmp(forward[i+1] ,"-") == 0) { i++; continue; }
      argv3[k++] = forward[i];
    }
  } else {
    for (int i = 0; forward[i]; ++i) argv3[k++] = forward[i];
  }
  argv3[k] = NULL;

  /* inner exists? (don’t force root ownership for unpriv tests) */
  struct stat st;
  if (stat(inner ,&st) != 0) die("inner not found: %s" ,inner);

  execv(python ,argv3);
  die("execv(%s) failed: %s" ,python ,strerror(errno));
}
