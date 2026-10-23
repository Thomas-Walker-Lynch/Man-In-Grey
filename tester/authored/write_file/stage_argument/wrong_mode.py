# A wrong argument: the journal interface raises an error, and no journal reaches the gate.

def compose(prov ,journal_iface):
  journal_iface.open("out" ,"unbound_conf" ,"overwrite" ,prov.process_user ,0o444)
