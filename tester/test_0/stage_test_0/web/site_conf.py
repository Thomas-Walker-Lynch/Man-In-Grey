# stage_test_0/web/site_conf.py

def configure(prov, planner, WriteFileMeta):
  # This writes a faux web config to .../stage_test_0/stage_test_0_out/web/nginx.conf
  wfm = WriteFileMeta(
    dpath="stage_test_0_out/web",
    fname="nginx.conf",             # explicit override (not from prov)
    owner=prov.process_user,
    mode="0644"
  )
  planner.displace(wfm)
  planner.copy(wfm, content="events {}\nhttp { server { listen 8080; } }\n")
