# unbound.conf (example)

def configure(prov, planner, WriteFileMeta):
  wfm = WriteFileMeta(
    dpath="stage_test_0_out"
    ,fname=prov.read_fname # write file name same as read file name
    ,owner=prov.process_user
   )
  planner.displace(wfm)
  planner.copy(wfm, content="server:\n  do-ip6: no\n")
