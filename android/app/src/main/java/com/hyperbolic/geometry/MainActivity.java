package com.hyperbolic.geometry;
import android.annotation.SuppressLint;
import android.app.Activity;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.ProgressBar;
import android.widget.RelativeLayout;
public class MainActivity extends Activity {
    private static final String URL = "https://hyperbolic-geometry-app.onrender.com";
        private WebView webView;
            @SuppressLint("SetJavaScriptEnabled")
                @Override
                    protected void onCreate(Bundle savedInstanceState) {
                            super.onCreate(savedInstanceState);
                                    RelativeLayout layout = new RelativeLayout(this);
                                            layout.setBackgroundColor(0xFF1a1a2e);
                                                    ProgressBar pb = new ProgressBar(this);
                                                            RelativeLayout.LayoutParams pbp = new RelativeLayout.LayoutParams(-2,-2);
                                                                    pbp.addRule(RelativeLayout.CENTER_IN_PARENT);
                                                                            layout.addView(pb, pbp);
                                                                                    webView = new WebView(this);
                                                                                            layout.addView(webView, new RelativeLayout.LayoutParams(-1,-1));
                                                                                                    setContentView(layout);
                                                                                                            WebSettings s = webView.getSettings();
                                                                                                                    s.setJavaScriptEnabled(true);
                                                                                                                            s.setDomStorageEnabled(true);
                                                                                                                                    s.setUseWideViewPort(true);
                                                                                                                                            s.setLoadWithOverviewMode(true);
                                                                                                                                                    webView.setWebViewClient(new WebViewClient() {
                                                                                                                                                                @Override public void onPageFinished(WebView v, String u) {
                                                                                                                                                                                pb.setVisibility(View.GONE);
                                                                                                                                                                                                webView.setVisibility(View.VISIBLE);
                                                                                                                                                                                                            }
                                                                                                                                                                                                                    });
                                                                                                                                                                                                                            pb.setVisibility(View.VISIBLE);
                                                                                                                                                                                                                                    webView.setVisibility(View.INVISIBLE);
                                                                                                                                                                                                                                            webView.loadUrl(URL);
                                                                                                                                                                                                                                                }
                                                                                                                                                                                                                                                    @Override public void onBackPressed() {
                                                                                                                                                                                                                                                            if (webView.canGoBack()) webView.goBack();
                                                                                                                                                                                                                                                                    else super.onBackPressed();
                                                                                                                                                                                                                                                                        }
                                                                                                                                                                                                                                                                        }