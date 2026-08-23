-- Add container restarting transition state.
-- MySQL ENUM columns must be altered before Ctrl can persist Node WSS snapshots
-- containing "restarting".

ALTER TABLE containers
  MODIFY COLUMN container_status ENUM(
    'online',
    'offline',
    'creating',
    'starting',
    'restarting',
    'stopping',
    'failed',
    'paused'
  ) NOT NULL DEFAULT 'creating';
