# replace_keep, under a file name given here rather than implied.

def compose(prov ,journal_iface):
  file = journal_iface.open("out/web" ,"nginx.conf" ,"replace_keep" ,prov.process_user ,"0644")
  journal_iface.write(file ,"events {}\nhttp { server { listen 8080; } }\n")
