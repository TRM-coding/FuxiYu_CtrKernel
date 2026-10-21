-- 容器清理提醒：从"每次发送记一行"改为"一行一档位状态"（2026-09）
--
-- 症状：机器进入不可用窗口后，同一容器每 20 分钟收到一封同样的提醒（生产实测 89 封）。
-- 成因：判重键里带着 cleanup_at，而顺延会把它持续前移——窗口还开着时按
--       "now - unavailable_since" 折算，cleanup_at 与 now 同步前进，精确匹配必然失败，
--       于是每轮扫描都判成新周期、重发一封。
-- 修法：reminder_key 改作**状态位**（该 (容器, 收件人) 已提醒到的最深档位），
--       判重只比档位、不比时间；周期变更时由 ssh upsert 把它打回 'NEVER'。
--
-- 存量行的档位描述的是早已过去的周期，对当前周期不成立，所以一律打回 'NEVER'。
-- 代价：处于提醒阈值内的容器各补发至多一封——按当前数据量就是 daity(166) 那一封。

-- 1) 折叠成"一行一 (容器, 收件人)"：同组只留最新一行。
--    必须排在改值**之前**：旧唯一键把 cleanup_at 也算进去，而同一周期的多个档位
--    （如容器 139 的 72h/24h/12h）cleanup_at 相同——一起改成 'NEVER' 会当场撞旧约束。
DELETE r1 FROM container_cleanup_reminders r1
JOIN container_cleanup_reminders r2
  ON r1.container_id = r2.container_id
 AND r1.recipient_email = r2.recipient_email
 AND r2.id > r1.id;

-- 2) 档位状态化：存量一律视为"本周期尚未提醒"
--
--    注意：若某容器此刻正处在某个提醒档内，打回 NEVER 会让它在下一轮扫描补发一封。
--    通用迁移不做这个判定——它得现算倒计时，而代价不过是每个这样的容器补发一封。
--    本次生产升级里 daity(166) 正处在 72h 档，且已因该缺陷被反复提醒了 89 次，
--    所以额外手工置回 '72h'（既不再骚扰，也更如实：它确实已被告知过 72h 档）。
--    若你要在别的环境重放本迁移，先查一遍有没有处在档内的容器，按需照做：
--      SELECT c.id, c.name FROM container_ssh_login_records s
--        JOIN containers c ON c.id = s.container_id
--       WHERE c.is_valid = 1 AND c.deleted_at IS NULL;
--    再逐个核对 build_cleanup_info 的 seconds_until_cleanup 是否落进某个阈值。
UPDATE container_cleanup_reminders SET reminder_key = 'NEVER';

-- 3) 唯一约束从 (容器, 档位, 到期时刻, 收件人) 收敛为 (容器, 收件人)
ALTER TABLE container_cleanup_reminders
  DROP INDEX uq_container_cleanup_reminder_once;

ALTER TABLE container_cleanup_reminders
  ADD UNIQUE KEY uq_container_cleanup_reminder_once (container_id, recipient_email);
