-- Add container building transition state for image build/create split.

ALTER TABLE containers
  MODIFY COLUMN container_status ENUM(
    'online',
    'offline',
    'building',
    'creating',
    'starting',
    'restarting',
    'stopping',
    'failed',
    'paused'
  ) NOT NULL DEFAULT 'creating';
