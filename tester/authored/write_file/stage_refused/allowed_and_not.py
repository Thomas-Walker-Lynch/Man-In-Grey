# One file the constraints allow, and one they do not. The whole journal is refused.

def compose(prov ,journal_iface):
  allowed = journal_iface.open("out" ,"unbound_conf" ,"replace_keep" ,prov.process_user ,0o444)
  journal_iface.write(allowed ,"this is not to be written\n")
  forbidden = journal_iface.open("out" ,"forbidden.conf" ,"replace" ,prov.process_user ,0o644)
  journal_iface.write(forbidden ,"nor this\n")
