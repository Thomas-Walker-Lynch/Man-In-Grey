# replace: the second run discards the first run's file, keeping no backup.
# The content is written in two parts.

def compose(prov ,journal_iface):
  file = journal_iface.open("out/net" ,prov.implied_fname ,"replace" ,prov.process_user ,"0444")
  journal_iface.write(file ,"server:\n")
  journal_iface.write(file ,"  verbosity: 1\n")
