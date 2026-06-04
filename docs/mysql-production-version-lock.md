# MySQL Production Version Lock

The current production MySQL package set is locked to:

- `mysql-server-8.0=8.0.46-0ubuntu0.24.04.2`
- `mysql-server-core-8.0=8.0.46-0ubuntu0.24.04.2`
- `mysql-client-8.0=8.0.46-0ubuntu0.24.04.2`
- `mysql-client-core-8.0=8.0.46-0ubuntu0.24.04.2`
- `mysql-server=8.0.46-0ubuntu0.24.04.2`
- `mysql-common=5.8+1.1.0build1`

Apply the lock:

```bash
cd /home/wyw/FuxiYu_CtrKernel
sudo bash scripts/lock_mysql_production_version.sh
```

Verify the lock:

```bash
apt-mark showhold | grep -E '^mysql'
apt-cache policy mysql-server-8.0 mysql-client-8.0 mysql-server-core-8.0 mysql-client-core-8.0 mysql-server mysql-common
mysql --version
systemctl status mysql --no-pager
```

Temporarily unlock for a planned upgrade:

```bash
sudo apt-mark unhold mysql-client-8.0 mysql-client-core-8.0 mysql-common mysql-server mysql-server-8.0 mysql-server-core-8.0
sudo rm -f /etc/apt/preferences.d/mysql-production-lock
```

After an upgrade is tested and accepted, update `scripts/lock_mysql_production_version.sh` and this document with the new package versions, then run the lock script again.
