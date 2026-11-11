ALTER TABLE containers ADD COLUMN failed_reason VARCHAR(255) NULL;
ALTER TABLE containers ADD COLUMN failed_detail TEXT NULL;
