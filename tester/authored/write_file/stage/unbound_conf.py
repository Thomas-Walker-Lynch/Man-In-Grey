# replace_keep: the second run keeps the first run's file as a timestamped backup.
# The file name is the one this composer implies: its own name less .py.

def compose(prov ,journal_iface):
  file = journal_iface.open("out" ,prov.implied_fname ,"replace_keep" ,prov.process_user ,0o444)
  journal_iface.write(file ,"server:\n  do-ip6: no\n")
