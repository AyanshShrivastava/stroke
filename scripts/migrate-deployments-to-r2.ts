#!/usr/bin/env tsx
/**
 * CLI Entrypoint: Migrate Historical Firestore Deployments to Cloudflare R2
 *
 * Usage:
 *   npx tsx scripts/migrate-deployments-to-r2.ts             # Dry run (safe inspection)
 *   npx tsx scripts/migrate-deployments-to-r2.ts --apply     # Execute live migration
 *   npx tsx scripts/migrate-deployments-to-r2.ts --verbose   # Detailed output
 */

import { migrateDeploymentsToR2 } from '../src/server/deploymentMigration';
import { initAdminFirestore } from '../src/server/firestoreAdmin';

async function main() {
  const args = process.argv.slice(2);
  const apply = args.includes('--apply');
  const dryRun = args.includes('--dry-run') || !apply;
  const verbose = args.includes('--verbose') || args.includes('-v');

  console.log('='.repeat(70));
  console.log(' Mist Cloudflare R2 Deployment Migration Tool');
  console.log('='.repeat(70));
  console.log(` Mode:    ${dryRun ? '🔍 DRY RUN (no writes will be made)' : '🚀 LIVE APPLY'}`);
  console.log(` Target:  Cloudflare R2 (bucket: ${process.env.R2_BUCKET_NAME || 'mist-published-sites'})`);
  console.log('='.repeat(70));

  if (dryRun && !args.includes('--dry-run')) {
    console.log('ℹ Notice: Running in preview dry-run mode. To apply changes to Firestore and R2, run with --apply.\n');
  }

  const firestore = initAdminFirestore();
  if (!firestore) {
    console.error('❌ Error: Could not connect to Firebase Firestore. Ensure Firebase Admin credentials are configured.');
    process.exit(1);
  }

  try {
    const report = await migrateDeploymentsToR2({
      apply,
      dryRun,
      verbose,
      firestore,
    });

    console.log('\nMigration Summary:');
    console.log(`  Total deployments found: ${report.totalFound}`);
    console.log(`  ${dryRun ? 'Eligible for migration' : 'Successfully migrated'}: ${report.migratedCount}`);
    console.log(`  Already in R2 (skipped): ${report.alreadyMigratedCount}`);
    console.log(`  Failed:                  ${report.failedCount}`);

    if (report.items.length > 0) {
      console.log('\nDetails:');
      for (const item of report.items) {
        const icon =
          item.status === 'migrated'
            ? '✅'
            : item.status === 'already_migrated'
              ? '⏭️'
              : item.status === 'failed'
                ? '❌'
                : '⚠️';
        const byteInfo = item.bytes ? ` (${Math.round(item.bytes / 1024)} KB)` : '';
        const errorInfo = item.error ? ` [Error: ${item.error}]` : '';
        console.log(`  ${icon} [${item.status.toUpperCase()}] ${item.slug}${byteInfo}${errorInfo}`);
      }
    }

    console.log('\n' + '='.repeat(70));
    if (dryRun && report.migratedCount > 0) {
      console.log('👉 To perform the live migration, execute:');
      console.log('   npm run migrate:deployments -- --apply');
    } else if (report.failedCount > 0) {
      console.log('⚠️ Some deployments encountered errors. Inspect the logs above.');
      process.exit(1);
    } else {
      console.log('✨ All deployments are properly synchronized with Cloudflare R2.');
    }
  } catch (err: any) {
    console.error('\n❌ Fatal migration error:', err.message || err);
    process.exit(1);
  }
}

main().catch((err) => {
  console.error('Unhandled error:', err);
  process.exit(1);
});
