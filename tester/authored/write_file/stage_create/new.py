# create: allowed once; a second run is refused, as the file then exists.

def compose(prov ,journal_iface):
  file = journal_iface.open("out" ,"new.conf" ,"create" ,prov.process_user ,0o600)
  journal_iface.write(file ,"made once\n")
