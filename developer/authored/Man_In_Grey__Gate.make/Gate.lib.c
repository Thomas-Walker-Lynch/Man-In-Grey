/*
  Man_In_Grey__Gate·Gate - the gate of a Man-In-Grey instruction language.

  A gate is a program of its own, made from this module by a three-line
  *.CLI.c whose main calls Man_In_Grey__Gate·Gate·run with three things fixed
  at compile time: the name of the instruction language, the guard's path and
  the interpreter's path, the two paths relative to the gate itself. The
  gate invoking account can name neither program; who invokes a gate cannot
  choose what it runs.

  Setuid and owned by account B, a gate starts with the effective uid of
  account B and the real uid of account A, the gate invoking account. Not
  setuid, it keeps both uids of the program that invoked it.

  admit:

    0. settles what the invoking program handed it: puts every signal's
       disposition back to its default, cancels the interval timers and
       clears the blocked mask, so a signal already pending is delivered now;
       opens /dev/null on any of descriptors 0, 1 and 2 left closed, keeps
       descriptor 3, the result descriptor, when the invoking program left it
       open and opens /dev/null there when it did not, and closes every
       descriptor above 3; and raises each resource limit that
       could stop the guard or the interpreter partway, refusing when one
       stays too low;
    1. refuses unless the guard and the interpreter, and every directory
       above them, are owned by root or by the effective uid's account and
       writable by no other account;
    2. clears the environment, sets the file mode mask to 077, marks the
       process not dumpable, changes directory to /, and records account A
       in MIG__REAL_UID, MIG__REAL_GID and MIG__REAL_USER_NAME;
    3. reads the journal from standard input;
    4. isolates itself from account A, when the two accounts differ: makes
       its real uid account B's, so the kernel refuses account A's signals,
       and ignores the signals a terminal sends;
    5. starts the guard with the journal on its standard input, and admits
       the journal only when the guard exits 0 having written exactly one
       line to standard output: guard <language> check passed;
    6. starts the interpreter with the same journal, and takes the journal
       as played only when the interpreter exits 0 having written exactly one
       line to standard output: interpreter <language> journal played;
    7. forwards the interpreter's result, what it wrote on its descriptor 3,
       to the gate's own descriptor 3, and only once the journal is taken as
       played: the bytes, and the open descriptors sent beside them.

  The guard is given no descriptor 3. The interpreter's descriptor 3 is one
  end of a Unix socket pair whose other end the gate holds. The gate reads it
  as it reads the interpreter's other output, up to RESULT_MAX bytes, and
  never examines the bytes. The interpreter can send open descriptors beside
  them, as SCM_RIGHTS, up to DESCRIPTOR_MAX; the gate keeps them, and hands
  them on with the bytes. Descriptors can travel only over a Unix socket, so
  a result that holds any is handed back only when the gate's own
  descriptor 3 is one; a result of bytes alone goes through a pipe too.

  The guard and the interpreter inherit the gate's uids and its ignored
  signals, and learn account A from MIG__REAL_UID and MIG__REAL_USER_NAME.

  The constraints are code installed with the guard, so nothing about them is
  given to the gate.

  The gate logs each journal's course itself, whatever the guard and the
  interpreter write: received, then approved or refused, then interpreting,
  then interpreted or failed. Every line the guard and the interpreter
  write is copied to the person and to the system log as well. A line that
  is not UTF-8, or holds a control character, or is too long, or one line
  too many, breaks the gate's rules: the gate stops the program and
  refuses.

  Exit status: 0 when the journal was admitted and executed, or admitted
  with check-only; 1 when the guard refused it or execution failed; 2 when
  the gate, guard or interpreter could not run, or broke the gate's rules.
*/

#ifndef Man_In_Grey__Gate·Gate·ONCE
#define Man_In_Grey__Gate·Gate·ONCE

int Man_In_Grey__Gate·Gate·run(
  const char *language
  ,const char *fpr__guard
  ,const char *fpr__interpreter
  ,int argc
  ,char **argv
);

#ifdef Man_In_Grey__Gate·Gate

  #include <dirent.h>
  #include <errno.h>
  #include <fcntl.h>
  #include <grp.h>
  #include <libgen.h>
  #include <limits.h>
  #include <poll.h>
  #include <pwd.h>
  #include <signal.h>
  #include <stdarg.h>
  #include <stdio.h>
  #include <stdlib.h>
  #include <string.h>
  #include <sys/prctl.h>
  #include <sys/resource.h>
  #include <sys/socket.h>
  #include <sys/stat.h>
  #include <sys/time.h>
  #include <sys/types.h>
  #include <sys/wait.h>
  #include <syslog.h>
  #include <unistd.h>

  #define PYTHON "/usr/bin/python3"
  #define JOURNAL_MAX ((size_t)16 << 20)
  #define OUTPUT_LINE__MAX 4096
  #define COUNT_OF__OUTPUT_LINE__MAX 2000
  #define VERDICT_MAX 512
  #define RESULT_MAX ((size_t)16 << 20)
  #define DESCRIPTOR_MAX 16
  #define RESULT_FD 3

  Local const char *Language = "";
  Local bool Logging = false;
  Local bool Result_discarded = false;   // descriptor 3 was not open, so a result goes to /dev/null

  // ------------------------------------------------------------------------------
  // saying things: to the person on standard error, and to the system log

  Local void say(const char *tag ,const char *format ,...){
    char message[OUTPUT_LINE__MAX + 128];
    va_list ap; va_start(ap ,format);
    vsnprintf(message ,sizeof message ,format ,ap);
    va_end(ap);
    fprintf(stderr ,"gate: %s: %s\n" ,tag ,message);
    if( Logging ) syslog(LOG_NOTICE ,"%s gate: %s: %s" ,Language ,tag ,message);
  }

  Local void die(const char *format ,...){
    char message[OUTPUT_LINE__MAX];
    va_list ap; va_start(ap ,format);
    vsnprintf(message ,sizeof message ,format ,ap);
    va_end(ap);
    say("cannot-run" ,"%s" ,message);
    _exit(2);
  }

  // ------------------------------------------------------------------------------
  // the ownership check

  /* path and every directory above it: owned by root or by the interpreter
     account, the effective uid, and writable by no other account */
  Local void check_trusted_owner(const char *path){
    uid_t interpreter_uid = geteuid();
    char prefix[PATH_MAX];
    size_t length = strlen(path);
    if( length >= sizeof prefix ) die("path too long: %s" ,path);
    struct stat st;
    if( lstat("/" ,&st) != 0 || st.st_uid != 0 ) die("/ is not owned by root");
    for(size_t i = 1; i <= length; ++i){
      if( i < length && path[i] != '/' ) continue;
      memcpy(prefix ,path ,i); prefix[i] = '\0';
      if( lstat(prefix ,&st) != 0 ) die("cannot examine %s: %s" ,prefix ,strerror(errno));
      if( st.st_uid != 0 && st.st_uid != interpreter_uid )
        die("%s is owned by uid %ld, neither root nor the effective uid's account" ,prefix ,(long)st.st_uid);
      if( st.st_mode & (S_IWGRP | S_IWOTH) )
        die("%s is writable by group or other accounts" ,prefix);
    }
  }

  // ------------------------------------------------------------------------------
  // what the invoking program hands the gate

  /* Signal state survives exec. The invoking program can leave a signal
     ignored, leave signals blocked with some already pending, and leave an
     interval timer running that will send SIGALRM, SIGVTALRM or SIGPROF
     later. The kernel sends a timer's signal to the gate itself, with no
     check of who set the timer, so any of these could act after the gate has
     isolated itself from account A. The gate puts it all back to the state a
     fresh process has: each disposition to its default, the timers off, the
     mask empty. Clearing the mask delivers any signal already pending, now,
     while the gate has done nothing that would need undoing. */
  Local void settle_signals(void){
    struct sigaction initial = {.sa_handler = SIG_DFL};
    sigemptyset(&initial.sa_mask);
    for(int signal_number = 1; signal_number < NSIG; ++signal_number){
      if( signal_number == SIGKILL || signal_number == SIGSTOP ) continue;   // never caught, never ignored
      sigaction(signal_number ,&initial ,NULL);   // refused, harmlessly, for numbers the C library keeps
    }
    struct itimerval off = {0};
    setitimer(ITIMER_REAL ,&off ,NULL);
    setitimer(ITIMER_VIRTUAL ,&off ,NULL);
    setitimer(ITIMER_PROF ,&off ,NULL);
    sigset_t empty;
    sigemptyset(&empty);
    sigprocmask(SIG_SETMASK ,&empty ,NULL);
  }

  /* Descriptors 0, 1 and 2 open, on /dev/null when the invoking program left
     one closed, so a pipe the gate makes cannot land on one of them.
     Descriptor 3 is the result descriptor: the invoking program opens it to
     receive the interpreter's result. When it is open the gate keeps it,
     marked close-on-exec so that neither the guard nor the interpreter
     inherits it; when it is not, the gate opens /dev/null there, and a
     result is discarded. Every other descriptor is closed, so nothing the
     invoking program opened reaches the guard or the interpreter. */
  Local void settle_descriptors(void){
    for(int fd = 0; fd <= RESULT_FD; ++fd){
      if( fcntl(fd ,F_GETFD) >= 0 ) continue;
      if( fd == RESULT_FD ) Result_discarded = true;
      int null = open("/dev/null" ,fd == RESULT_FD ? O_WRONLY : O_RDWR);
      if( null < 0 ) die("cannot open /dev/null: %s" ,strerror(errno));
      if( null != fd ){
        if( dup2(null ,fd) < 0 ) die("cannot open descriptor %d: %s" ,fd ,strerror(errno));
        close(null);
      }
    }
    DIR *dir = opendir("/proc/self/fd");
    if( !dir ) die("cannot list /proc/self/fd: %s" ,strerror(errno));
    int own = dirfd(dir);
    size_t count = 0 ,size = 64;
    int *list = malloc(size * sizeof *list);
    if( !list ) die("out of memory");
    struct dirent *entry;
    while( (entry = readdir(dir)) ){
      char *end;
      long fd = strtol(entry->d_name ,&end ,10);
      if( *end || end == entry->d_name || fd <= RESULT_FD || fd == own ) continue;
      if( count == size ){
        size *= 2;
        int *larger = realloc(list ,size * sizeof *list);
        if( !larger ) die("out of memory");
        list = larger;
      }
      list[count++] = (int)fd;
    }
    closedir(dir);
    for(size_t i = 0; i < count; ++i) close(list[i]);
    free(list);
    int flags = fcntl(RESULT_FD ,F_GETFD);
    if( flags < 0 || fcntl(RESULT_FD ,F_SETFD ,flags | FD_CLOEXEC) < 0 )
      die("cannot set close-on-exec on descriptor %d: %s" ,RESULT_FD ,strerror(errno));
  }

  typedef struct{
    int resource;
    const char *name;
    rlim_t need;             // RLIM_INFINITY when the limit is to be unlimited
  } Limit;

  Local void say_limit(char *text ,size_t size ,rlim_t value){
    if( value == RLIM_INFINITY ) snprintf(text ,size ,"unlimited");
    else snprintf(text ,size ,"%llu" ,(unsigned long long)value);
  }

  /* The invoking program sets the resource limits the gate starts with. A
     small file size or CPU time limit would stop the interpreter partway
     through a journal. Each limit is raised to what the gate needs, as far
     as the hard limit allows, or past it when account B is root; the gate
     refuses when a limit stays too low. */
  Local void settle_limits(void){
    const Limit list__limit[] = {
      {RLIMIT_FSIZE ,"file size (bytes)" ,RLIM_INFINITY}
      ,{RLIMIT_CPU ,"CPU time (seconds)" ,RLIM_INFINITY}
      ,{RLIMIT_AS ,"address space (bytes)" ,(rlim_t)1 << 30}
      ,{RLIMIT_DATA ,"data size (bytes)" ,(rlim_t)1 << 30}
      ,{RLIMIT_STACK ,"stack size (bytes)" ,(rlim_t)8 << 20}
      ,{RLIMIT_NOFILE ,"open files" ,64}
    };
    for(size_t i = 0; i < sizeof list__limit / sizeof list__limit[0]; ++i){
      const Limit *limit = &list__limit[i];
      struct rlimit r;
      if( getrlimit(limit->resource ,&r) != 0 ) die("cannot read the %s limit: %s" ,limit->name ,strerror(errno));
      if( r.rlim_cur >= limit->need ) continue;
      if( geteuid() == 0 && r.rlim_max < limit->need ) r.rlim_max = limit->need;
      r.rlim_cur = r.rlim_max < limit->need ? r.rlim_max : limit->need;
      setrlimit(limit->resource ,&r);
      if( getrlimit(limit->resource ,&r) != 0 ) die("cannot read the %s limit: %s" ,limit->name ,strerror(errno));
      if( r.rlim_cur < limit->need ){
        char have[32] ,want[32];
        say_limit(have ,sizeof have ,r.rlim_cur);
        say_limit(want ,sizeof want ,limit->need);
        die("the %s limit is %s; the gate needs %s" ,limit->name ,have ,want);
      }
    }
  }

  // the program at a path relative to the gate's own directory, resolved
  Local bool resolve(const char *relative ,char *resolved){
    char exe[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe" ,exe ,sizeof exe - 1);
    if( n < 0 ) return false;
    exe[n] = '\0';
    char candidate[PATH_MAX];
    if( snprintf(candidate ,sizeof candidate ,"%s/%s" ,dirname(exe) ,relative) >= (int)sizeof candidate ) return false;
    return realpath(candidate ,resolved) != NULL;
  }

  // a language name: not empty, no space, no control character
  Local bool is__valid_name(const char *name){
    if( !*name ) return false;
    for(const unsigned char *p = (const unsigned char *)name; *p; ++p)
      if( *p <= 0x20 || *p == 0x7F ) return false;
    return true;
  }

  // ------------------------------------------------------------------------------
  // the rules for what the guard and the interpreter write

  /* true when the line is UTF-8 holding no control character: none of C0,
     DEL or C1, no overlong form, no surrogate */
  Local bool is__clean_line(const unsigned char *s ,size_t n){
    size_t i = 0;
    while( i < n ){
      unsigned c = s[i];
      if( c < 0x80 ){
        if( c < 0x20 || c == 0x7F ) return false;
        ++i; continue;
      }
      unsigned code; size_t length;
      if( (c & 0xE0) == 0xC0 ){ code = c & 0x1F; length = 2; }
      else if( (c & 0xF0) == 0xE0 ){ code = c & 0x0F; length = 3; }
      else if( (c & 0xF8) == 0xF0 ){ code = c & 0x07; length = 4; }
      else return false;
      if( i + length > n ) return false;
      for(size_t k = 1; k < length; ++k){
        unsigned d = s[i + k];
        if( (d & 0xC0) != 0x80 ) return false;
        code = (code << 6) | (d & 0x3F);
      }
      if( (length == 2 && code < 0x80) || (length == 3 && code < 0x800) || (length == 4 && code < 0x10000) ) return false;
      if( code > 0x10FFFF || (code >= 0xD800 && code <= 0xDFFF) ) return false;
      if( code >= 0x80 && code <= 0x9F ) return false;
      i += length;
    }
    return true;
  }

  typedef struct{
    int fd;
    FILE *echo;              // where its lines are copied for the person
    const char *stream;      // "stdout" or "stderr", for the log
    char line[OUTPUT_LINE__MAX];
    size_t length;
  } Stream;

  typedef struct{
    const char *source;      // "guard" or "interpreter"
    bool is__stdout_verdict;  // standard output is kept as the verdict, not shown
    bool has__result;         // given a descriptor 3, whose bytes are kept as its result
    char verdict[VERDICT_MAX];
    size_t verdict_length;
    unsigned char *result;
    size_t result_length;
    size_t result_size;
    int list__descriptor[DESCRIPTOR_MAX];   // sent beside the result, kept close-on-exec
    size_t count_of__descriptor;
    size_t count_of__line;
    const char *broken;      // the rule broken, or NULL
  } Child;

  Local void finish_line(Child *child ,Stream *stream){
    if( child->broken ) return;
    if( !is__clean_line((unsigned char *)stream->line ,stream->length) ){
      child->broken = "a line that is not UTF-8 or holds a control character";
      return;
    }
    if( ++child->count_of__line > COUNT_OF__OUTPUT_LINE__MAX ){
      child->broken = "more lines than the gate accepts";
      return;
    }
    stream->line[stream->length] = '\0';
    fprintf(stream->echo ,"%s: %s\n" ,child->source ,stream->line);
    fflush(stream->echo);
    syslog(LOG_NOTICE ,"%s %s: %s" ,Language ,child->source ,stream->line);
    stream->length = 0;
  }

  Local void take(Child *child ,Stream *stream ,const char *bytes ,size_t n){
    for(size_t i = 0; i < n && !child->broken; ++i){
      if( bytes[i] == '\n' ){ finish_line(child ,stream); continue; }
      if( stream->length == OUTPUT_LINE__MAX - 1 ){ child->broken = "a line longer than the gate accepts"; return; }
      stream->line[stream->length++] = bytes[i];
    }
  }

  Local void take_verdict(Child *child ,const char *bytes ,size_t n){
    if( child->verdict_length + n > VERDICT_MAX - 1 ){ child->broken = "more on standard output than a verdict"; return; }
    memcpy(child->verdict + child->verdict_length ,bytes ,n);
    child->verdict_length += n;
    child->verdict[child->verdict_length] = '\0';
  }

  Local void take_result(Child *child ,const char *bytes ,size_t n){
    if( child->result_length + n > RESULT_MAX ){ child->broken = "a result larger than the gate accepts"; return; }
    if( child->result_length + n > child->result_size ){
      size_t size = child->result_size ? child->result_size : 1 << 12;
      while( size < child->result_length + n ) size *= 2;
      unsigned char *larger = realloc(child->result ,size);
      if( !larger ) die("out of memory");
      child->result = larger;
      child->result_size = size;
    }
    memcpy(child->result + child->result_length ,bytes ,n);
    child->result_length += n;
  }

  /* Read the interpreter's result socket: bytes into buffer, and every
     descriptor sent beside them as SCM_RIGHTS into the child's list. The
     kernel opens a received descriptor in this process; MSG_CMSG_CLOEXEC
     keeps it from any program the gate starts. One past DESCRIPTOR_MAX
     breaks the gate's rules, and MSG_CTRUNC, the kernel saying it dropped
     descriptors there was no room for, does too. */
  Local ssize_t receive_result(Child *child ,int fd ,char *buffer ,size_t size){
    union{ struct cmsghdr align; char space[CMSG_SPACE(sizeof(int) * DESCRIPTOR_MAX)]; } control;
    struct iovec iov = {.iov_base = buffer ,.iov_len = size};
    struct msghdr message = {.msg_iov = &iov ,.msg_iovlen = 1 ,.msg_control = control.space ,.msg_controllen = sizeof control.space};
    ssize_t n = recvmsg(fd ,&message ,MSG_CMSG_CLOEXEC);
    if( n < 0 ) return n;
    for(struct cmsghdr *c = CMSG_FIRSTHDR(&message); c; c = CMSG_NXTHDR(&message ,c)){
      if( c->cmsg_level != SOL_SOCKET || c->cmsg_type != SCM_RIGHTS ) continue;
      size_t count = (c->cmsg_len - CMSG_LEN(0)) / sizeof(int);
      for(size_t i = 0; i < count; ++i){
        int received;
        memcpy(&received ,CMSG_DATA(c) + i * sizeof(int) ,sizeof received);
        if( child->count_of__descriptor == DESCRIPTOR_MAX ){
          close(received);
          child->broken = "more descriptors beside its result than the gate accepts";
          continue;
        }
        child->list__descriptor[child->count_of__descriptor++] = received;
      }
    }
    if( message.msg_flags & MSG_CTRUNC ) child->broken = "more descriptors beside its result than the gate accepts";
    return n;
  }

  Local void close_descriptor(Child *child){
    for(size_t i = 0; i < child->count_of__descriptor; ++i) close(child->list__descriptor[i]);
    child->count_of__descriptor = 0;
  }

  Local void close_on_exec(int fd){
    int flags = fcntl(fd ,F_GETFD);
    if( flags < 0 || fcntl(fd ,F_SETFD ,flags | FD_CLOEXEC) < 0 ) die("cannot set close-on-exec: %s" ,strerror(errno));
  }

  /* Start PYTHON with the arguments, give it the input on its standard input,
     and read its standard output and standard error by the gate's rules.
     Returns the wait status. */
  Local int run_child(Child *child ,char *const argument[] ,const unsigned char *input ,size_t input_length){
    int in[2] ,out[2] ,err[2] ,res[2] = {-1 ,-1};
    if( pipe(in) || pipe(out) || pipe(err) ) die("cannot make a pipe: %s" ,strerror(errno));
    if( child->has__result && socketpair(AF_UNIX ,SOCK_STREAM ,0 ,res) ) die("cannot make a socket pair: %s" ,strerror(errno));
    for(int k = 0; k < 2; ++k){
      close_on_exec(in[k]); close_on_exec(out[k]); close_on_exec(err[k]);
      if( child->has__result ) close_on_exec(res[k]);
    }

    pid_t pid = fork();
    if( pid < 0 ) die("cannot start the %s: %s" ,child->source ,strerror(errno));
    if( pid == 0 ){
      if( dup2(in[0] ,0) < 0 || dup2(out[1] ,1) < 0 || dup2(err[1] ,2) < 0 ) _exit(127);
      if( child->has__result && dup2(res[1] ,RESULT_FD) < 0 ) _exit(127);
      execv(PYTHON ,argument);
      dprintf(2 ,"cannot-start: %s: %s\n" ,PYTHON ,strerror(errno));
      _exit(127);
    }
    close(in[0]); close(out[1]); close(err[1]);
    if( child->has__result ) close(res[1]);
    fcntl(in[1] ,F_SETFL ,fcntl(in[1] ,F_GETFL) | O_NONBLOCK);

    Stream out_stream = {.fd = out[0] ,.echo = stdout ,.stream = "stdout"};
    Stream err_stream = {.fd = err[0] ,.echo = stderr ,.stream = "stderr"};
    int in_fd = in[1];
    int res_fd = child->has__result ? res[0] : -1;
    size_t written = 0;
    if( input_length == 0 ){ close(in_fd); in_fd = -1; }

    while( (out_stream.fd >= 0 || err_stream.fd >= 0 || res_fd >= 0) && !child->broken ){
      struct pollfd list__poll[4];
      int count = 0 ,in_at = -1 ,out_at = -1 ,err_at = -1 ,res_at = -1;
      if( in_fd >= 0 ){ list__poll[count] = (struct pollfd){.fd = in_fd ,.events = POLLOUT}; in_at = count++; }
      if( res_fd >= 0 ){ list__poll[count] = (struct pollfd){.fd = res_fd ,.events = POLLIN}; res_at = count++; }
      if( out_stream.fd >= 0 ){ list__poll[count] = (struct pollfd){.fd = out_stream.fd ,.events = POLLIN}; out_at = count++; }
      if( err_stream.fd >= 0 ){ list__poll[count] = (struct pollfd){.fd = err_stream.fd ,.events = POLLIN}; err_at = count++; }
      if( poll(list__poll ,count ,-1) < 0 ){
        if( errno == EINTR ) continue;
        die("poll: %s" ,strerror(errno));
      }
      if( in_at >= 0 && list__poll[in_at].revents ){
        ssize_t n = write(in_fd ,input + written ,input_length - written);
        if( n > 0 ) written += (size_t)n;
        if( (n < 0 && errno != EAGAIN && errno != EINTR) || written == input_length ){ close(in_fd); in_fd = -1; }
      }
      if( res_at >= 0 && list__poll[res_at].revents ){
        char buffer[4096];
        ssize_t n = receive_result(child ,res_fd ,buffer ,sizeof buffer);
        if( n > 0 ) take_result(child ,buffer ,(size_t)n);
        else if( n == 0 || (errno != EAGAIN && errno != EINTR) ){ close(res_fd); res_fd = -1; }
      }
      Stream *list__stream[2] = {&out_stream ,&err_stream};
      int list__at[2] = {out_at ,err_at};
      for(int k = 0; k < 2; ++k){
        Stream *stream = list__stream[k];
        if( list__at[k] < 0 || !list__poll[list__at[k]].revents ) continue;
        char buffer[4096];
        ssize_t n = read(stream->fd ,buffer ,sizeof buffer);
        if( n < 0 && (errno == EAGAIN || errno == EINTR) ) continue;
        if( n <= 0 ){
          if( stream->length > 0 && !(stream == &out_stream && child->is__stdout_verdict) ) finish_line(child ,stream);
          close(stream->fd); stream->fd = -1;
          continue;
        }
        if( stream == &out_stream && child->is__stdout_verdict ) take_verdict(child ,buffer ,(size_t)n);
        else take(child ,stream ,buffer ,(size_t)n);
      }
    }

    if( child->broken ){ kill(pid ,SIGKILL); close_descriptor(child); }
    if( in_fd >= 0 ) close(in_fd);
    if( res_fd >= 0 ) close(res_fd);
    if( out_stream.fd >= 0 ) close(out_stream.fd);
    if( err_stream.fd >= 0 ) close(err_stream.fd);
    int status = 0;
    while( waitpid(pid ,&status ,0) < 0 ){
      if( errno != EINTR ) die("waitpid: %s" ,strerror(errno));
    }
    return status;
  }

  // ------------------------------------------------------------------------------
  // the commands

  Local void print_usage(FILE *file ,const char *program){
    fprintf(file ,
      "Usage: %s <command> [option ...]\n"
      "  help | -h            print this message (also printed when given no arguments)\n"
      "  flags                print the real and effective ids, whether they differ, the\n"
      "                       instruction language, and the paths of the guard and interpreter\n"
      "  admit [option ...]   read a journal on standard input, run the guard, and when the\n"
      "                       guard passes the journal, run the interpreter\n"
      "Option of admit:\n"
      "  check-only           run the guard and not the interpreter\n"
      "A journal that declares a result has it written to descriptor 3 once the\n"
      "journal is played; when descriptor 3 is not open, the result is discarded.\n"
      "A result holding descriptors needs descriptor 3 to be a Unix socket.\n"
      ,program
    );
  }

  Local const char *user_name(uid_t uid){
    struct passwd *pw = getpwuid(uid);
    return pw ? pw->pw_name : "unknown";
  }

  Local const char *group_name(gid_t gid){
    struct group *gr = getgrgid(gid);
    return gr ? gr->gr_name : "unknown";
  }

  Local void print_flags(const char *fpr__guard ,const char *fpr__interpreter){
    printf("real.uid=%ld\n" ,(long)getuid());
    printf("real.user-name=%s\n" ,user_name(getuid()));
    printf("real.gid=%ld\n" ,(long)getgid());
    printf("real.group-name=%s\n" ,group_name(getgid()));
    printf("effective.uid=%ld\n" ,(long)geteuid());
    printf("effective.user-name=%s\n" ,user_name(geteuid()));
    printf("effective.gid=%ld\n" ,(long)getegid());
    printf("effective.group-name=%s\n" ,group_name(getegid()));
    printf("uid-differ=%d\n" ,getuid() != geteuid() ? 1 : 0);
    printf("gid-differ=%d\n" ,getgid() != getegid() ? 1 : 0);
    printf("language=%s\n" ,Language);
    char resolved[PATH_MAX];
    printf("guard.path=%s\n" ,resolve(fpr__guard ,resolved) ? resolved : "(missing)");
    printf("interpreter.path=%s\n" ,resolve(fpr__interpreter ,resolved) ? resolved : "(missing)");
  }

  // ------------------------------------------------------------------------------
  // isolation from account A

  /* The kernel lets a process signal another when the sender's real or
     effective uid matches the target's real or saved uid. A setuid gate
     starts with account A as its real uid, so account A can signal it,
     SIGKILL and SIGSTOP included, which no handler can catch.

     A process may set its real uid to its effective uid. Once the journal
     is read, the gate does, and setreuid then sets the saved uid to account
     B as well. With all three uids account B's, the kernel refuses account
     A's signals before delivering anything. A terminal sends its signals to
     the foreground process group without that check, so the gate ignores
     them; the guard and the interpreter inherit both the uids and the
     ignored signals.

     When accounts A and B are the same there is nothing to isolate, and the
     person can still interrupt his own run. Returns whether the gate
     isolated itself. */
  Local bool isolate_from_invoker(void){
    uid_t account_B = geteuid();
    if( getuid() == account_B ) return false;
    if( setreuid(account_B ,account_B) != 0 ) die("cannot set the real uid to account B's: %s" ,strerror(errno));
    if( getuid() != account_B || geteuid() != account_B ) die("the real uid did not become account B's");
    int terminal_signal[] = {SIGINT ,SIGQUIT ,SIGTSTP ,SIGTTIN ,SIGTTOU ,SIGHUP};
    for(size_t i = 0; i < sizeof terminal_signal / sizeof terminal_signal[0]; ++i){
      signal(terminal_signal[i] ,SIG_IGN);
    }
    return true;
  }

  Local void wait_writable(void){
    struct pollfd p = {.fd = RESULT_FD ,.events = POLLOUT};
    poll(&p ,1 ,-1);
  }

  /* Write the result to descriptor 3, all of it, waiting while the
     invoking program's end of it is full. Descriptors go with the first
     bytes, as SCM_RIGHTS, so descriptor 3 has to be a Unix socket when there
     are any; when it is not, nothing is written and errno is ENOTSOCK.
     Returns false when it cannot. */
  Local bool forward_result(const unsigned char *result ,size_t length ,const int *list__descriptor ,size_t count){
    size_t written = 0;
    if( count > 0 ){
      struct stat st;
      if( fstat(RESULT_FD ,&st) != 0 ) return false;
      if( !S_ISSOCK(st.st_mode) ){ errno = ENOTSOCK; return false; }
      union{ struct cmsghdr align; char space[CMSG_SPACE(sizeof(int) * DESCRIPTOR_MAX)]; } control;
      memset(&control ,0 ,sizeof control);
      struct iovec iov = {.iov_base = (void *)result ,.iov_len = length};
      struct msghdr message = {.msg_iov = &iov ,.msg_iovlen = 1 ,.msg_control = control.space
                               ,.msg_controllen = CMSG_SPACE(sizeof(int) * count)};
      struct cmsghdr *c = CMSG_FIRSTHDR(&message);
      c->cmsg_level = SOL_SOCKET;
      c->cmsg_type = SCM_RIGHTS;
      c->cmsg_len = CMSG_LEN(sizeof(int) * count);
      memcpy(CMSG_DATA(c) ,list__descriptor ,sizeof(int) * count);
      for(;;){
        ssize_t n = sendmsg(RESULT_FD ,&message ,MSG_NOSIGNAL);
        if( n > 0 ){ written = (size_t)n; break; }
        if( n < 0 && errno == EINTR ) continue;
        if( n < 0 && errno == EAGAIN ){ wait_writable(); continue; }
        return false;
      }
    }
    while( written < length ){
      ssize_t n = write(RESULT_FD ,result + written ,length - written);
      if( n > 0 ){ written += (size_t)n; continue; }
      if( n < 0 && errno == EINTR ) continue;
      if( n < 0 && errno == EAGAIN ){ wait_writable(); continue; }
      return false;
    }
    return true;
  }

  Local unsigned char *read_journal(size_t *length){
    size_t size = 1 << 16;
    unsigned char *journal = malloc(size);
    if( !journal ) die("out of memory");
    *length = 0;
    for(;;){
      if( *length == size ){
        if( size >= JOURNAL_MAX ) die("the journal is larger than %zu bytes" ,(size_t)JOURNAL_MAX);
        size *= 2;
        unsigned char *larger = realloc(journal ,size);
        if( !larger ) die("out of memory");
        journal = larger;
      }
      ssize_t n = read(0 ,journal + *length ,size - *length);
      if( n < 0 ){
        if( errno == EINTR ) continue;
        die("cannot read the journal: %s" ,strerror(errno));
      }
      if( n == 0 ) break;
      *length += (size_t)n;
    }
    return journal;
  }

  int Man_In_Grey__Gate·Gate·run(
    const char *language
    ,const char *fpr__guard
    ,const char *fpr__interpreter
    ,int argc
    ,char **argv
  ){
    Language = language;
    const char *program = argc > 0 ? argv[0] : "gate";
    if( argc < 2 || !strcmp(argv[1] ,"help") || !strcmp(argv[1] ,"-h") || !strcmp(argv[1] ,"--help") ){
      print_usage(stdout ,program);
      return 0;
    }
    if( !strcmp(argv[1] ,"flags") && argc == 2 ){
      print_flags(fpr__guard ,fpr__interpreter);
      return 0;
    }
    if( strcmp(argv[1] ,"admit") ){
      fprintf(stderr ,"gate: usage: unknown command '%s'\n" ,argv[1]);
      print_usage(stderr ,program);
      return 2;
    }
    bool check_only = false;
    for(int i = 2; i < argc; ++i){
      if( !strcmp(argv[i] ,"check-only") ){ check_only = true; continue; }
      fprintf(stderr ,"gate: usage: unknown or incomplete option '%s'\n" ,argv[i]);
      return 2;
    }

    settle_signals();
    settle_descriptors();
    settle_limits();

    if( !is__valid_name(language) ) die("the language name compiled into this gate is empty or holds a space or control character");
    char fpa__guard[PATH_MAX] ,fpa__interpreter[PATH_MAX];
    if( !resolve(fpr__guard ,fpa__guard) ) die("the guard is missing: %s" ,fpr__guard);
    if( !resolve(fpr__interpreter ,fpa__interpreter) ) die("the interpreter is missing: %s" ,fpr__interpreter);
    check_trusted_owner(fpa__guard);
    check_trusted_owner(fpa__interpreter);

    uid_t real_uid = getuid();
    gid_t real_gid = getgid();
    char real_user__name[256];
    snprintf(real_user__name ,sizeof real_user__name ,"%s" ,user_name(real_uid));

    clearenv();
    setenv("PATH" ,"/usr/sbin:/usr/bin:/sbin:/bin" ,1);
    setenv("LANG" ,"C.UTF-8" ,1);
    char number[32];
    snprintf(number ,sizeof number ,"%ld" ,(long)real_uid); setenv("MIG__REAL_UID" ,number ,1);
    snprintf(number ,sizeof number ,"%ld" ,(long)real_gid); setenv("MIG__REAL_GID" ,number ,1);
    setenv("MIG__REAL_USER_NAME" ,real_user__name ,1);
    umask(077);
    prctl(PR_SET_DUMPABLE ,0 ,0 ,0 ,0);
    if( chdir("/") != 0 ) die("cannot change directory to /");
    signal(SIGPIPE ,SIG_IGN);

    openlog("Man-In-Grey_gate" ,LOG_PID ,LOG_AUTHPRIV);
    Logging = true;

    size_t journal_length;
    unsigned char *journal = read_journal(&journal_length);
    say("received" ,"real uid %ld (%s), effective uid %ld (%s), journal of %zu bytes%s"
        ,(long)real_uid ,real_user__name ,(long)geteuid() ,user_name(geteuid()) ,journal_length ,check_only ? ", check only" : "");
    if( isolate_from_invoker() ){
      say("isolated" ,"real uid now %ld (%s); account A can no longer signal the gate" ,(long)getuid() ,user_name(getuid()));
    }

    // the guard
    char *guard_argument[] = {
      (char *)PYTHON ,(char *)"-E" ,(char *)"-s" ,(char *)"-B" ,fpa__guard ,(char *)"check" ,NULL
    };
    Child guard = {.source = "guard" ,.is__stdout_verdict = true};
    int status = run_child(&guard ,guard_argument ,journal ,journal_length);
    if( guard.broken ){
      say("refused" ,"the guard broke the gate's rules: %s" ,guard.broken);
      return 2;
    }
    char expected[VERDICT_MAX];
    snprintf(expected ,sizeof expected ,"guard %s check passed\n" ,language);
    if( !WIFEXITED(status) ){
      say("refused" ,"the guard was stopped by signal %d" ,WIFSIGNALED(status) ? WTERMSIG(status) : 0);
      return 2;
    }
    if( WEXITSTATUS(status) == 1 ){
      say("refused" ,"by the guard");
      return 1;
    }
    if( WEXITSTATUS(status) != 0 ){
      say("refused" ,"the guard could not check the journal (exit status %d)" ,WEXITSTATUS(status));
      return 2;
    }
    if( strcmp(guard.verdict ,expected) ){
      say("refused" ,"the guard exited 0 without writing the one line 'guard %s check passed'" ,language);
      return 2;
    }
    say("approved" ,"guard %s check passed" ,language);
    if( check_only ){
      say("not-interpreted" ,"check-only was asked");
      return 0;
    }

    // the interpreter
    char *interpreter_argument[] = {
      (char *)PYTHON ,(char *)"-E" ,(char *)"-s" ,(char *)"-B" ,fpa__interpreter ,(char *)"execute" ,NULL
    };
    Child interpreter = {.source = "interpreter" ,.is__stdout_verdict = true ,.has__result = true};
    say("interpreting" ,"%s" ,fpa__interpreter);
    status = run_child(&interpreter ,interpreter_argument ,journal ,journal_length);
    if( interpreter.broken ){
      say("failed" ,"the interpreter broke the gate's rules: %s; what it had done stays done" ,interpreter.broken);
      return 2;
    }
    if( !WIFEXITED(status) ){
      say("failed" ,"the interpreter was stopped by signal %d" ,WIFSIGNALED(status) ? WTERMSIG(status) : 0);
      return 2;
    }
    if( WEXITSTATUS(status) == 1 ){
      say("failed" ,"the interpreter stopped partway; what it had done stays done");
      return 1;
    }
    if( WEXITSTATUS(status) != 0 ){
      say("failed" ,"the interpreter could not run (exit status %d)" ,WEXITSTATUS(status));
      return 2;
    }
    snprintf(expected ,sizeof expected ,"interpreter %s journal played\n" ,language);
    if( strcmp(interpreter.verdict ,expected) ){
      say("failed" ,"the interpreter exited 0 without writing the one line 'interpreter %s journal played'; what it did stays done" ,language);
      return 2;
    }
    say("interpreted" ,"interpreter %s journal played" ,language);
    if( interpreter.result_length > 0 ){
      size_t count = interpreter.count_of__descriptor;
      if( Result_discarded )
        say("result-discarded" ,"%zu bytes and %zu descriptors; descriptor 3 was not open" ,interpreter.result_length ,count);
      else if( forward_result(interpreter.result ,interpreter.result_length ,interpreter.list__descriptor ,count) )
        say("result-forwarded" ,"%zu bytes and %zu descriptors on descriptor 3" ,interpreter.result_length ,count);
      else if( errno == ENOTSOCK )
        say("result-lost" ,"%zu bytes and %zu descriptors; descriptor 3 is not a Unix socket, which descriptors need" ,interpreter.result_length ,count);
      else
        say("result-lost" ,"%zu bytes and %zu descriptors; descriptor 3 cannot be written: %s" ,interpreter.result_length ,count ,strerror(errno));
    }
    close_descriptor(&interpreter);
    return 0;
  }

#endif // Man_In_Grey__Gate·Gate
#endif // Man_In_Grey__Gate·Gate·ONCE
