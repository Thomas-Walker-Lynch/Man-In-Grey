# composer_channel/channel.py
#
# A journal whose result is a descriptor: the reading end of a pipe holding
# CONTENT. The orchestrator prints it as <descriptor> and closes it.

CONTENT = b"through the gate\n"

def compose(prov ,journal_iface):
  channel = journal_iface.declare("channel" ,"channel")
  journal_iface.channel(CONTENT ,channel)
  journal_iface.result(channel)
