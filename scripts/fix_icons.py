# Run inside `odoo-bin shell` (env is provided). Repairs a DB restored without filestore.
import os
fs = env['ir.attachment']._filestore()
env.cr.execute("SELECT id, store_fname, res_model, url FROM ir_attachment WHERE store_fname IS NOT NULL")
rows = env.cr.fetchall()
missing = [r for r in rows if not os.path.exists(os.path.join(fs, r[1]))]
print(f"FIX_ICONS filestore={fs} stored={len(rows)} missing_files={len(missing)}")
# 1. menu icons
menus = env['ir.ui.menu'].with_context(active_test=False).search([('web_icon', '!=', False)])
n = 0
for m in menus:
    try:
        data = m._compute_web_icon_data(m.web_icon)
    except Exception as e:
        print(f"FIX_ICONS skip menu {m.id} {m.web_icon}: {e}")
        continue
    m.web_icon_data = data or False
    n += 1
print(f"FIX_ICONS menus_rebuilt={n}")
# 2. asset bundles (regenerated on demand)
assets = env['ir.attachment'].sudo().search([('url', '=like', '/web/assets/%')])
print(f"FIX_ICONS asset_attachments_deleted={len(assets)}")
assets.unlink()
env.registry.clear_cache('assets') if hasattr(env.registry, 'clear_cache') else None
env.cr.commit()
env.cr.execute("SELECT store_fname FROM ir_attachment WHERE store_fname IS NOT NULL")
left = sum(1 for (f,) in env.cr.fetchall() if not os.path.exists(os.path.join(fs, f)))
print(f"FIX_ICONS still_missing_files={left} (non-icon binaries; need --with-filestore to recover)")
