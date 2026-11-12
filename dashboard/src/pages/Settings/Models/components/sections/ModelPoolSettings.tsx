/**
 * ModelPoolSettings — per-model round-robin switch, participating members,
 * and the fallback chain ("三层保险": main pool → fallback models in order).
 *
 * Lives under the model pool list on the chat-models tab.
 */
import { useCallback, useEffect, useState } from "react";
import { ArrowDown, ArrowUp, Info, Plus, Trash2 } from "lucide-react";
import { Button, Checkbox, Empty, Input, Switch, Tag, Tooltip } from "antd";
import { message } from "@/utils/antdMessage";

import { useTranslation } from "react-i18next";
import { modelPoolsApi } from "../../../../../api/modules/modelPools";
import type {
  ModelPool,
  ModelPoolSaveItem,
} from "../../../../../api/modules/modelPools";
import styles from "../../index.module.less";

export function ModelPoolSettings() {
  const { t } = useTranslation();
  const [pools, setPools] = useState<ModelPool[] | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [newFallback, setNewFallback] = useState<Record<string, string>>({});

  const fetchPools = useCallback(async () => {
    try {
      const data = await modelPoolsApi.list();
      setPools(data.pools);
      setDirty(false);
    } catch (err) {
      message.error(
        err instanceof Error ? err.message : t("common.saveFailed"),
      );
    }
  }, [t]);

  useEffect(() => {
    void fetchPools();
  }, [fetchPools]);

  const updatePool = (modelId: string, patch: Partial<ModelPool>) => {
    setPools((prev) =>
      prev === null
        ? prev
        : prev.map((pool) =>
            pool.model_id === modelId ? { ...pool, ...patch } : pool,
          ),
    );
    setDirty(true);
  };

  const handleToggleMember = (
    modelId: string,
    ref: string,
    checked: boolean,
  ) => {
    setPools((prev) =>
      prev === null
        ? prev
        : prev.map((pool) =>
            pool.model_id === modelId
              ? {
                  ...pool,
                  members: pool.members.map((member) =>
                    member.ref === ref
                      ? { ...member, enabled: checked }
                      : member,
                  ),
                }
              : pool,
          ),
    );
    setDirty(true);
  };

  const handleFallbackChange = (
    modelId: string,
    index: number,
    value: string,
  ) => {
    setPools((prev) =>
      prev === null
        ? prev
        : prev.map((pool) =>
            pool.model_id === modelId
              ? {
                  ...pool,
                  fallbacks: pool.fallbacks.map((item, i) =>
                    i === index ? value : item,
                  ),
                }
              : pool,
          ),
    );
    setDirty(true);
  };

  const handleMoveFallback = (
    modelId: string,
    index: number,
    direction: -1 | 1,
  ) => {
    const pool = pools?.find((item) => item.model_id === modelId);
    if (!pool) return;
    const target = index + direction;
    if (target < 0 || target >= pool.fallbacks.length) return;
    const fallbacks = [...pool.fallbacks];
    [fallbacks[index], fallbacks[target]] = [
      fallbacks[target],
      fallbacks[index],
    ];
    updatePool(modelId, { fallbacks });
  };

  const handleAddFallback = (modelId: string) => {
    const value = (newFallback[modelId] ?? "").trim();
    if (!value) return;
    if (!value.includes("/")) {
      message.warning(t("models.modelPoolFallbackFormat"));
      return;
    }
    const pool = pools?.find((item) => item.model_id === modelId);
    if (!pool) return;
    if (pool.fallbacks.includes(value)) {
      message.warning(t("models.modelPoolFallbackExists"));
      return;
    }
    updatePool(modelId, { fallbacks: [...pool.fallbacks, value] });
    setNewFallback((prev) => ({ ...prev, [modelId]: "" }));
  };

  const handleSave = async () => {
    if (pools === null) return;
    const body: ModelPoolSaveItem[] = pools.map((pool) => ({
      model_id: pool.model_id,
      enabled: pool.enabled,
      members: pool.members
        .filter((member) => member.enabled)
        .map((m) => m.ref),
      fallbacks: pool.fallbacks.map((ref) => ref.trim()).filter(Boolean),
    }));
    setSaving(true);
    try {
      const data = await modelPoolsApi.save(body);
      setPools(data.pools);
      setDirty(false);
      message.success(t("models.modelPoolSaved"));
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
          <h3 className={styles.slotTitle}>
            {t("models.modelPoolConfigTitle")}
          </h3>
          <Tooltip title={t("models.modelPoolConfigTooltip")}>
            <Info size={14} className={styles.poolInfoIcon} />
          </Tooltip>
        </div>
      </div>

      <p className={styles.poolDesc}>{t("models.modelPoolConfigDesc")}</p>

      {pools === null ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("common.loading")}
        />
      ) : pools.length === 0 ? (
        <Empty
          image={Empty.PRESENTED_IMAGE_SIMPLE}
          description={t("models.modelPoolConfigEmpty")}
        />
      ) : (
        <>
          <div className={styles.poolList}>
            {pools.map((pool) => (
              <div key={pool.model_id} className={styles.poolGroup}>
                <div className={styles.poolGroupHeader}>
                  <div className={styles.poolGroupHeaderLeft}>
                    <span className={styles.poolGroupName}>
                      {pool.model_id}
                    </span>
                    <Tag className={styles.poolGroupKind}>
                      {t("models.modelPoolMemberCount", {
                        count: pool.members.length,
                      })}
                    </Tag>
                  </div>
                  <span
                    style={{ display: "flex", alignItems: "center", gap: 8 }}
                  >
                    <span
                      style={{ fontSize: 12, color: "var(--fn-text-tertiary)" }}
                    >
                      {t("models.modelPoolRoundRobin")}
                    </span>
                    <Switch
                      checked={pool.enabled}
                      onChange={(checked) =>
                        updatePool(pool.model_id, { enabled: checked })
                      }
                    />
                  </span>
                </div>

                <div style={{ padding: "12px 16px", display: "grid", gap: 12 }}>
                  {!pool.enabled && (
                    <div
                      style={{ fontSize: 12, color: "var(--fn-text-tertiary)" }}
                    >
                      {t("models.modelPoolRoundRobinOff")}
                    </div>
                  )}

                  <div>
                    <div
                      style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}
                    >
                      {t("models.modelPoolMembers")}
                    </div>
                    <div style={{ display: "grid", gap: 4 }}>
                      {pool.members.map((member) => (
                        <Checkbox
                          key={member.ref}
                          checked={member.enabled}
                          disabled={!member.usable}
                          onChange={(e) =>
                            handleToggleMember(
                              pool.model_id,
                              member.ref,
                              e.target.checked,
                            )
                          }
                        >
                          {member.ref}
                          {!member.usable && (
                            <Tag color="default" style={{ marginLeft: 8 }}>
                              {t("models.modelPoolUnavailable")}
                            </Tag>
                          )}
                        </Checkbox>
                      ))}
                    </div>
                  </div>

                  <div>
                    <div
                      style={{ fontSize: 12, fontWeight: 600, marginBottom: 6 }}
                    >
                      {t("models.modelPoolFallbacks")}
                    </div>
                    <div
                      style={{
                        fontSize: 12,
                        color: "var(--fn-text-tertiary)",
                        marginBottom: 6,
                      }}
                    >
                      {t("models.modelPoolFallbackHint")}
                    </div>
                    <div style={{ display: "grid", gap: 6 }}>
                      {pool.fallbacks.map((ref, index) => (
                        <div
                          key={`${pool.model_id}-${index}`}
                          style={{
                            display: "flex",
                            gap: 6,
                            alignItems: "center",
                          }}
                        >
                          <Input
                            value={ref}
                            placeholder={t(
                              "models.modelPoolFallbackPlaceholder",
                            )}
                            onChange={(e) =>
                              handleFallbackChange(
                                pool.model_id,
                                index,
                                e.target.value,
                              )
                            }
                          />
                          <Button
                            type="text"
                            size="small"
                            disabled={index === 0}
                            icon={<ArrowUp size={14} />}
                            onClick={() =>
                              handleMoveFallback(pool.model_id, index, -1)
                            }
                          />
                          <Button
                            type="text"
                            size="small"
                            disabled={index === pool.fallbacks.length - 1}
                            icon={<ArrowDown size={14} />}
                            onClick={() =>
                              handleMoveFallback(pool.model_id, index, 1)
                            }
                          />
                          <Button
                            type="text"
                            size="small"
                            danger
                            icon={<Trash2 size={14} />}
                            onClick={() =>
                              updatePool(pool.model_id, {
                                fallbacks: pool.fallbacks.filter(
                                  (_, i) => i !== index,
                                ),
                              })
                            }
                          />
                        </div>
                      ))}
                      <div style={{ display: "flex", gap: 6 }}>
                        <Input
                          value={newFallback[pool.model_id] ?? ""}
                          placeholder={t("models.modelPoolFallbackPlaceholder")}
                          onChange={(e) =>
                            setNewFallback((prev) => ({
                              ...prev,
                              [pool.model_id]: e.target.value,
                            }))
                          }
                          onPressEnter={() => handleAddFallback(pool.model_id)}
                        />
                        <Button
                          icon={<Plus size={14} />}
                          onClick={() => handleAddFallback(pool.model_id)}
                        >
                          {t("models.modelPoolFallbackAdd")}
                        </Button>
                      </div>
                    </div>
                  </div>
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
