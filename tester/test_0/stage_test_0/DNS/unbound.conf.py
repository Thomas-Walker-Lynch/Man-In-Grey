# stage_test_0/DNS/unbound_conf.py

def configure(prov, planner, WriteFileMeta):
  # dpath is relative; it will be anchored to prov.read_dir_dpath,
  # so this lands in .../stage_test_0/stage_test_0_out/dns
  wfm = WriteFileMeta(
    dpath="stage_test_0_out/net",
    fname=prov.read_fname,          # "unbound_conf"
    owner=prov.process_user,        # current process user
    mode=0o444
  )
  planner.delete(wfm)
  planner.copy(wfm, content="server:\n  verbosity: 1\n")
