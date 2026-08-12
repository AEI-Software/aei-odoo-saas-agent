import { session } from "@web/session";
import { registry } from "@web/core/registry";

// Odoo 19: many2one_field.js no longer exports `many2OneField` — the field
// description is built inline (buildM2OFieldDescription) and only lives in
// the "fields" registry. Importing the removed export left the symbol
// undefined and patch(undefined) crashed the WHOLE webclient at boot
// (ModuleLoader TypeError, SUB00264 2026-08-12). Wrap the registry entry's
// extractProps instead.
const many2OneField = registry.category("fields").get("many2one");
const extractProps = many2OneField.extractProps;

many2OneField.extractProps = (staticInfo, dynamicInfo) => {
    const res = extractProps(staticInfo, dynamicInfo);
    if (
        session.disable_quick_create &&
        staticInfo.options.no_quick_create == undefined
    ) {
        res.canQuickCreate = false;
    }
    return res;
};
