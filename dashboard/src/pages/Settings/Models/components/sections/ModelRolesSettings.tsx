/**
 * ModelRolesSettings — pick which models are primary, backup, and last resort.
 *
 * Three multi-selects, no model name hard-coded: every usable model ref is
 * an option in each multi-select. The automatic route rotates across the
 * models of the primary role, then the backup role, then the last resort.
 * Lives on the chat-models tab, below the model pool section.
 */
import { useCallback, useEffect, useState } from "react";
import { Info } from "lucide-react";
import { Button, Empty, Select, Tooltip } from "antd";
import { message } from "@/utils/antdMessage";

import { useTranslation } from "react-i18next";
import { modelRolesApi } from "../../../../../api/modules/modelRoles";
import styles from "../../index.module.less";

type RoleKey = "primary" | "backup" | "last_resort";

const ROLE_KEYS: RoleKey[] = ["primary", "backup", "last_resort"];

const ROLE_LABEL_KEY: Record<RoleKey, string> = {
  primary: "models.modelRolesPrimary",
  backup: "models.modelRolesBackup",
  last_resort: "models.modelRolesLastResort",
};

const ROLE_HINT_KEY: Record<RoleKey, string> = {
  primary: "models.modelRolesPrimaryHint",
  backup: "models.modelRolesBackupHint",
  last_resort: "models.modelRolesLastResortHint",
};

export function ModelRolesSettings() {
  const { t } = useTranslation();
  const [roles, setRoles] = useState<Record<RoleKey, string[]> | null>(null);
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);

  const fetchRoles = useCallback(async () => {
    try {
      const data = await modelRolesApi.get();
      setRoles({
        primary: data.primary,
        backup: data.backup,
        last_resort: data.last_resort,
      });
      // All usable models, no cap — the multi-select scrolls when the list is long.
      setAvailableModels(data.available_models);
      setDirty(false);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("common.saveFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void fetchRoles();
  }, [fetchRoles]);

  const handleChange = (key: RoleKey, value: string[]) => {
    setRoles((prev) => (prev === null ? prev : { ...prev, [key]: value }));
    setDirty(true);
  };

  const handleSave = async () => {
    if (roles === null) return;
    setSaving(true);
    try {
      const data = await modelRolesApi.save(roles);
      setRoles({
        primary: data.primary,
        backup: data.backup,
        last_resort: data.last_resort,
      });
      setAvailableModels(data.available_models);
      setDirty(false);
      message.success(t("models.modelRolesSaved"));
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("common.saveFailed"),
      );
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className={styles.poolSection}>
      <div className={styles.poolHeader}>
        <div className={styles.poolHeaderLeft}>
          <h3 className={styles.slotTitle}>{t("models.modelRolesTitle")}</h3>
          <Tooltip title={t("models.modelRolesTooltip")}>
            <Info size={14} className={styles.poolInfoIcon} />
          </Tooltip>
        </div>
      </div>

      <p className={styles.poolDesc}>{t("models.modelRolesDesc")}</p>

      {roles === null ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("common.loading")}
        />
      ) : availableModels.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("models.modelRolesNoModels")}
        />
      ) : (
        <>
          <div style={{ display: "grid", gap: 16 }}>
            {ROLE_KEYS.map((key) => (
              <div key={key}>
                <div style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}>
                  {t(ROLE_LABEL_KEY[key])}
                </div>
                <Select
                  mode="multiple"
                  style={{ width: "100%" }}
                  showSearch
                  allowClear
                  value={roles[key]}
                  placeholder={t("models.modelRolesUnset")}
                  maxTagCount="responsive"
                  options={availableModels.map((ref) => ({
                    value: ref,
                    label: ref,
                  }))}
                  onChange={(value) => handleChange(key, value as string[])}
                />
                <div
                  style={{
                    fontSize: 12,
                    color: "var(--fn-text-tertiary)",
                    marginTop: 4,
                  }}
                >
                  {t(ROLE_HINT_KEY[key])}
                </div>
              </div>
            ))}
          </div>

          <div
            style={{
              marginTop: 16,
              display: "flex",
              justifyContent: "flex-end",
            }}
          >
            <Button
              type="primary"
              loading={saving}
              disabled={!dirty}
              onClick={() => void handleSave()}
            >
              {t("common.save")}
            </Button>
          </div>
        </>
      )}
    </div>
  );
}
