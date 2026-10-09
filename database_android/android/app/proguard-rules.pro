# google_mlkit_text_recognition references optional recognizers for scripts
# this app does not use. Japanese recognition is packaged explicitly in
# build.gradle.kts; suppress only the optional-language references.
-dontwarn com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.chinese.ChineseTextRecognizerOptions
-dontwarn com.google.mlkit.vision.text.devanagari.DevanagariTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.devanagari.DevanagariTextRecognizerOptions
-dontwarn com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions$Builder
-dontwarn com.google.mlkit.vision.text.korean.KoreanTextRecognizerOptions

# ML Kit finds its components by reflection (no-arg constructors of the *Registrar classes). R8 removed
# them in the release APK, so every text recognition failed with
# "Could not instantiate com.google.mlkit.vision.common.internal.VisionCommonRegistrar" and then
# "NullPointerException ... getClass()" (2026-10-09, Juggler Online trial; the screenshot import was
# affected the same way). Keep ML Kit and its internal Play-services classes as they are.
-keep class com.google.mlkit.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_vision_text_common.** { *; }
-keep class com.google.android.gms.internal.mlkit_common.** { *; }
-keepclassmembers class * implements com.google.firebase.components.ComponentRegistrar { public <init>(); }
