# Man_In_Grey acceptance filter (default template)
# Return True to include a config file ,False to skip it.
# You receive a PlanProvenance object named `prov`.
#
# Common fields:
#  prov.stage_root_dpath : Path
#  prov.config_abs_fpath : Path
#  prov.config_rel_fpath : Path
#  prov.read_dir_dpath   : Path
#  prov.read_fname       : str
#
# 1) Accept everything (default):
# def accept(prov):
#   return True
#
# 2) Only a namespace:
# def accept(prov):
#   return prov.config_rel_fpath.as_posix().startswith("dns/")
#
# 3) Exclude editor junk:
# def accept(prov):
#   r = prov.config_rel_fpath.as_posix()
#   return not (r.endswith("~") or r.endswith(".swp"))
#
def accept(prov):
  return True
