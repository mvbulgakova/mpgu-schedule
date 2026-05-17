package com.mvbulgakova.hyperbolicgeometryapp;

import android.os.Bundle;
import android.widget.TextView;
import androidx.appcompat.app.AppCompatActivity;
import com.chaquo.python.PyObject;
import com.chaquo.python.Python;

public class MainActivity extends AppCompatActivity {

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        TextView textView = findViewById(R.id.textView);

        if (!Python.isStarted()) {
            Python.start(new AndroidPlatform(this));
        }

        Python py = Python.getInstance();
        PyObject sphereApp = py.getModule("hyperbolic_sphere_app");

        PyObject result = sphereApp.callAttr("create_sphere_figure", 0.4, 0.1, -0.2, 0.3);
        textView.setText(result.toString());
    }
}