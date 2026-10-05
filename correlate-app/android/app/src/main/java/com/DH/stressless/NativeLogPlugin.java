package com.DH.stressless;

import android.util.Log;

import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

@CapacitorPlugin(name = "NativeLog")
public class NativeLogPlugin extends Plugin {
    @PluginMethod
    public void log(PluginCall call) {
        String level = call.getString("level", "ok");
        String message = call.getString("message", "");
        if ("error".equals(level)) {
            Log.e("AppLog", message);
        } else if ("warn".equals(level)) {
            Log.w("AppLog", message);
        } else {
            Log.d("AppLog", message);
        }
        call.resolve();
    }
}
