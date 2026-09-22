-- Cleanup deferral columns (2026-09)
--
-- Goal: machine-unavailable windows (offline / maintenance) must not count
-- against container ssh-expiry cleanup timing.  Two Ctrl-owned columns:
--   1. machines.unavailable_since            -- start of the current unavailable
--      window (set when entering offline/maintenance, cleared on recovery).
--   2. container_ssh_login_records.deferral_seconds -- accumulated deferral for
--      the machine's unavailable time, added in bulk when the window closes.
-- Both are Ctrl-owned only: they are never written by Node snapshot frames
-- (last_ssh_login_time is; deferral must survive frame overwrites).
--
-- MySQL / MariaDB production path.

ALTER TABLE machines
  ADD COLUMN unavailable_since DATETIME NULL;

ALTER TABLE container_ssh_login_records
  ADD COLUMN deferral_seconds INT NULL DEFAULT 0;
