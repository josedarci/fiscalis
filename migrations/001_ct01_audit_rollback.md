# CT-01 audit migration rollback

The recommended rollback is to deploy the prior application version and leave
the additive database schema in place. The audit columns are nullable, and the
added indexes do not require the prior application to use them.

Do not run destructive DDL as part of an application rollback. This migration
does not change existing `consultas_tributos` records, and retaining the
additive columns and indexes avoids risking data loss or downtime. If schema
removal is ever required, plan it as a separate, explicitly reviewed migration
after confirming no application version or retained audit data depends on it.

No destructive rollback SQL is provided.
