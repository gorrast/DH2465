package com.DH.stressless;

import android.Manifest;
import android.app.AppOpsManager;
import android.app.usage.UsageEvents;
import android.app.usage.UsageStats;
import android.app.usage.UsageStatsManager;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.content.pm.ResolveInfo;
import android.os.Process;
import android.provider.Settings;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.text.SimpleDateFormat;
import java.util.ArrayList;
import java.util.Calendar;
import java.util.Date;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

@CapacitorPlugin(name = "UsageStats")
public class UsageStatsPlugin extends Plugin {

    @SuppressWarnings("unused")
    @PluginMethod
    public void checkPermission(PluginCall call) {
        boolean granted = hasUsageStatsPermission();
        JSObject result = new JSObject();
        result.put("granted", granted);
        result.put("result", granted ? "granted" : "denied");
        call.resolve(result);
    }

    @SuppressWarnings("unused")
    @PluginMethod
    public void requestPermission(PluginCall call) {
        try {
            Intent intent = new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception e) {
            Logger.error("UsageStatsPlugin", "Error requesting permission", e);
            call.reject("Error requesting permission: " + e.getMessage());
        }
    }

    @SuppressWarnings("unused")
    @PluginMethod
    public void getUsageStats(PluginCall call) {
        if (!hasUsageStatsPermission()) {
            call.reject("Usage stats permission not granted");
            return;
        }

        Long startObj = call.getLong("startTime");
        Long endObj = call.getLong("endTime");
        long startVal = startObj != null ? startObj : 0L;
        long endVal = endObj != null ? endObj : 0L;

        // Default: yesterday 00:00:00.000 -> today 00:00:00.000 (device local time)
        if (startVal == 0 || endVal == 0) {
            Calendar cal = Calendar.getInstance();
            cal.set(Calendar.HOUR_OF_DAY, 0);
            cal.set(Calendar.MINUTE, 0);
            cal.set(Calendar.SECOND, 0);
            cal.set(Calendar.MILLISECOND, 0);
            long computedEnd = cal.getTimeInMillis();
            cal.add(Calendar.DAY_OF_YEAR, -1);
            long computedStart = cal.getTimeInMillis();

            if (startVal == 0) startVal = computedStart;
            if (endVal == 0) endVal = computedEnd;
        }

        long startTime = startVal;
        long endTime = endVal;

        UsageStatsManager usm = (UsageStatsManager) getContext().getSystemService(Context.USAGE_STATS_SERVICE);
        if (usm == null) {
            call.reject("UsageStatsManager not available");
            return;
        }

        String selfPkg = getContext().getPackageName();
        String defaultLauncherPkg = getDefaultLauncherPackage();

        Map<String, Long> totals = computeForegroundTimes(usm, startTime, endTime);

        List<Map.Entry<String, Long>> sortedEntries = new ArrayList<>(totals.entrySet());
        sortedEntries.sort((a, b) -> Long.compare(b.getValue(), a.getValue()));

        JSArray statsArray = new JSArray();
        long totalMsAll = 0L;
        StringBuilder top10Log = new StringBuilder();
        int rank = 0;

        for (Map.Entry<String, Long> entry : sortedEntries) {
            String pkg = entry.getKey();
            long totalTime = entry.getValue();

            // Exclude self, systemui, and default launcher
            if (pkg.equals(selfPkg)
                    || pkg.equals("com.android.systemui")
                    || Objects.equals(pkg, defaultLauncherPkg)
                    || totalTime <= 0L) {
                continue;
            }

            totalMsAll += totalTime;

            JSObject obj = new JSObject();
            obj.put("packageName", pkg);
            obj.put("totalTimeMillis", totalTime);
            statsArray.put(obj);

            if (rank < 10) {
                rank++;
                long mins = totalTime / 60000L;
                top10Log.append(String.format(Locale.US, "\n  #%d %s: %d ms (%d mins)", rank, pkg, totalTime, mins));
            }
        }

        SimpleDateFormat sdf = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS Z", Locale.getDefault());
        String startStr = sdf.format(new Date(startTime));
        String endStr = sdf.format(new Date(endTime));
        long totalMinsAll = totalMsAll / 60000L;

        Logger.info("UsageStatsPlugin", String.format(
                Locale.US,
                "Resolved UsageStats Window:\n  Start: %s (%d)\n  End:   %s (%d)\n  Total Duration: %d ms (%d mins)\nTop Packages:%s",
                startStr, startTime, endStr, endTime, totalMsAll, totalMinsAll, top10Log
        ));

        // TEMPORARY DEBUG: compare with Android's own daily bucket. Remove when done.
        logDailyBucketComparison(usm, startTime, endTime, selfPkg, defaultLauncherPkg);

        JSObject result = new JSObject();
        result.put("stats", statsArray);
        result.put("startTime", startTime);
        result.put("endTime", endTime);
        call.resolve(result);
    }

    private Map<String, Long> computeForegroundTimes(UsageStatsManager usm, long start, long end) {
        Map<String, Long> totals = new HashMap<>();
        Map<String, Set<String>> resumed = new HashMap<>(); // pkg -> currently resumed activities
        Map<String, Long> openSince = new HashMap<>();      // pkg -> when it became visible

        try {
            // Look back so apps already in the foreground at 00:00 are caught
            long queryStart = start - 6L * 60 * 60 * 1000;
            UsageEvents events = usm.queryEvents(queryStart, end);
            UsageEvents.Event e = new UsageEvents.Event();

            while (events.hasNextEvent()) {
                events.getNextEvent(e);
                String pkg = e.getPackageName();
                if (pkg == null) continue;
                String cls = e.getClassName() != null ? e.getClassName() : "";
                long ts = e.getTimeStamp();
                int type = e.getEventType();

                // TEMPORARY DEBUG: dump raw events for Messenger (verify the package name)
                if (pkg.equals("com.facebook.orca") && ts >= start && ts < end) {
                    Logger.info("UsageStatsPlugin", "EVT " + type + " " + cls + " @ " + ts);
                }

                switch (type) {
                    case UsageEvents.Event.ACTIVITY_RESUMED: {
                        Set<String> set = resumed.computeIfAbsent(pkg, k -> new HashSet<>());
                        if (set.isEmpty()) openSince.put(pkg, ts);
                        set.add(cls);
                        break;
                    }

                    case UsageEvents.Event.ACTIVITY_PAUSED:
                    case UsageEvents.Event.ACTIVITY_STOPPED: {
                        Set<String> set = resumed.get(pkg);
                        if (set == null) break;
                        set.remove(cls);
                        if (set.isEmpty()) {
                            resumed.remove(pkg);
                            Long since = openSince.remove(pkg);
                            if (since != null) addClipped(totals, pkg, since, ts, start, end);
                        }
                        break;
                    }

                    case UsageEvents.Event.SCREEN_NON_INTERACTIVE:
                    case UsageEvents.Event.DEVICE_SHUTDOWN: {
                        // Screen off closes everything, so a missed PAUSED can't count forever
                        for (Map.Entry<String, Long> o : openSince.entrySet()) {
                            addClipped(totals, o.getKey(), o.getValue(), ts, start, end);
                        }
                        openSince.clear();
                        resumed.clear();
                        break;
                    }
                }
            }

            // Still open at the end of the window
            for (Map.Entry<String, Long> o : openSince.entrySet()) {
                addClipped(totals, o.getKey(), o.getValue(), end, start, end);
            }
        } catch (Exception ex) {
            Logger.error("UsageStatsPlugin", "Error computing foreground times", ex);
        }
        return totals;
    }

    private void addClipped(Map<String, Long> totals, String pkg, long from, long to,
                            long winStart, long winEnd) {
        long s = Math.max(from, winStart);
        long t = Math.min(to, winEnd);
        if (t > s) totals.put(pkg, totals.getOrDefault(pkg, 0L) + (t - s));
    }

    // TEMPORARY DEBUG: logs Android's own daily bucket so you can compare it with
    // the event-based totals and with Digital Wellbeing.
    private void logDailyBucketComparison(UsageStatsManager usm, long startTime, long endTime,
                                          String selfPkg, String launcherPkg) {
        try {
            List<UsageStats> daily = usm.queryUsageStats(UsageStatsManager.INTERVAL_DAILY, startTime, endTime);
            long dailyTotal = 0L;
            if (daily != null) {
                for (UsageStats u : daily) {
                    // Only the bucket that belongs to the requested day
                    if (Math.abs(u.getFirstTimeStamp() - startTime) >= 12L * 60 * 60 * 1000) continue;

                    String pkg = u.getPackageName();
                    long fg = u.getTotalTimeInForeground();
                    if (pkg.equals(selfPkg) || pkg.equals("com.android.systemui")
                            || Objects.equals(pkg, launcherPkg)) continue;

                    dailyTotal += fg;
                    if (fg > 60000L) {
                        Logger.info("UsageStatsPlugin", "DAILY " + pkg + ": " + (fg / 60000L) + " min");
                    }
                }
            }
            Logger.info("UsageStatsPlugin", "DAILY total: " + (dailyTotal / 60000L) + " min");
        } catch (Exception ex) {
            Logger.error("UsageStatsPlugin", "Daily bucket comparison failed", ex);
        }
    }

    private String getDefaultLauncherPackage() {
        try {
            Intent intent = new Intent(Intent.ACTION_MAIN);
            intent.addCategory(Intent.CATEGORY_HOME);
            PackageManager pm = getContext().getPackageManager();
            ResolveInfo resolveInfo = pm.resolveActivity(intent, PackageManager.MATCH_DEFAULT_ONLY);
            if (resolveInfo != null && resolveInfo.activityInfo != null) {
                return resolveInfo.activityInfo.packageName;
            }
        } catch (Exception e) {
            Logger.error("UsageStatsPlugin", "Error getting default launcher package", e);
        }
        return null;
    }

    private boolean hasUsageStatsPermission() {
        AppOpsManager appOps = (AppOpsManager) getContext().getSystemService(Context.APP_OPS_SERVICE);
        int mode = appOps.checkOpNoThrow(
                AppOpsManager.OPSTR_GET_USAGE_STATS,
                Process.myUid(),
                getContext().getPackageName()
        );
        if (mode == AppOpsManager.MODE_DEFAULT) {
            return getContext().checkCallingOrSelfPermission(Manifest.permission.PACKAGE_USAGE_STATS)
                    == PackageManager.PERMISSION_GRANTED;
        }
        return mode == AppOpsManager.MODE_ALLOWED;
    }
}