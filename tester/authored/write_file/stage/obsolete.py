# unlink: the first run removes out/obsolete.conf; the second finds nothing to remove.

def compose(prov ,journal_iface):
  journal_iface.unlink("out" ,"obsolete.conf")
