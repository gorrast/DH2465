package com.DH.stressless;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(NativeLogPlugin.class);
        registerPlugin(UsageStatsPlugin.class);
        super.onCreate(savedInstanceState);
    }
}
