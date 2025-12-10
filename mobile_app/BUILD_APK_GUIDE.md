# Building APK for Coop Kiosk Mobile App

This guide explains how to build a standalone APK file for your Expo mobile app that can be installed independently on Android devices.

## Prerequisites

1. **Node.js** (v14 or higher) - Already installed
2. **Expo Account** (free) - Sign up at https://expo.dev
3. **EAS CLI** - Expo's build service CLI tool

## Method 1: Using EAS Build (Recommended - Cloud Build)

EAS Build is Expo's cloud-based build service. It's the easiest and most reliable method.

### Step 1: Install EAS CLI

```bash
npm install -g eas-cli
```

### Step 2: Login to Expo

```bash
eas login
```

Enter your Expo account credentials (create one at https://expo.dev if you don't have one).

### Step 3: Configure Your App

The `eas.json` file is already configured. Make sure your `app.json` has the correct package name:

```json
{
  "expo": {
    "android": {
      "package": "com.coopkiosk.mobile"
    }
  }
}
```

### Step 4: Update API Configuration for Production

Before building, update `mobile_app/config.js` with your production API URL:

```javascript
const PRODUCTION_URL = 'https://your-production-server.com'; // Update this!
```

### Step 5: Build APK

Navigate to the mobile_app directory and run:

```bash
cd mobile_app
eas build --platform android --profile preview
```

**Build Profiles:**
- `preview` - Builds an APK for testing (recommended for standalone installation)
- `production` - Builds an APK for production release
- `development` - Builds a development client

### Step 6: Download Your APK

1. The build will start in the cloud (takes 10-20 minutes)
2. You'll get a URL to track the build progress
3. Once complete, download the APK from the Expo dashboard or use:
   ```bash
   eas build:list
   ```
4. Install the APK on any Android device by transferring the file and enabling "Install from Unknown Sources"

## Method 2: Local Build (Advanced)

If you prefer to build locally without using Expo's cloud service:

### Prerequisites for Local Build

1. **Android Studio** - Install from https://developer.android.com/studio
2. **Java Development Kit (JDK)** - Version 11 or higher
3. **Android SDK** - Installed via Android Studio
4. **Environment Variables** - Set `ANDROID_HOME` and `JAVA_HOME`

### Step 1: Install EAS CLI

```bash
npm install -g eas-cli
```

### Step 2: Configure Local Build

Update `eas.json` to enable local builds:

```json
{
  "build": {
    "preview": {
      "distribution": "internal",
      "android": {
        "buildType": "apk",
        "gradleCommand": ":app:assembleRelease"
      }
    }
  }
}
```

### Step 3: Prebuild Native Code

```bash
cd mobile_app
npx expo prebuild --platform android
```

This generates the native Android project.

### Step 4: Build Locally

```bash
eas build --platform android --profile preview --local
```

**Note:** Local builds require significant setup and may take longer. Cloud builds are recommended for most users.

## Method 3: Using Expo Build Service (Legacy)

The older `expo build` command is deprecated but still works:

```bash
cd mobile_app
npx expo build:android -t apk
```

**Note:** This method is being phased out in favor of EAS Build.

## Installing the APK

Once you have your APK file:

1. **Transfer to Android Device:**
   - Email it to yourself
   - Use USB file transfer
   - Upload to Google Drive/Dropbox
   - Use ADB: `adb install app.apk`

2. **Enable Unknown Sources:**
   - Go to Settings > Security
   - Enable "Install from Unknown Sources" or "Install Unknown Apps"
   - Select your file manager app

3. **Install:**
   - Open the APK file on your device
   - Tap "Install"
   - Wait for installation to complete

## Troubleshooting

### Build Fails with "No credentials found"

Run:
```bash
eas credentials
```

Follow the prompts to set up Android credentials.

### Build Takes Too Long

Cloud builds typically take 10-20 minutes. Be patient, or try a local build if you have the setup.

### APK Won't Install

- Ensure "Install from Unknown Sources" is enabled
- Check that the APK is for the correct Android version
- Verify the APK file wasn't corrupted during download

### API Connection Issues

Make sure you've updated `PRODUCTION_URL` in `config.js` before building. The app will use this URL in production builds.

## Production Considerations

Before releasing your APK:

1. **Update API URL:** Set `PRODUCTION_URL` in `config.js` to your production server
2. **Test Thoroughly:** Install the APK on multiple devices and test all features
3. **Version Number:** Update version in `app.json` for each release
4. **App Signing:** For production releases, set up proper app signing via EAS credentials
5. **Permissions:** Review and update Android permissions in `app.json` if needed

## Quick Start (TL;DR)

```bash
# 1. Install EAS CLI
npm install -g eas-cli

# 2. Login
eas login

# 3. Build APK (from mobile_app directory)
cd mobile_app
eas build --platform android --profile preview

# 4. Download APK from Expo dashboard when build completes
# 5. Install on Android device
```

## Additional Resources

- [EAS Build Documentation](https://docs.expo.dev/build/introduction/)
- [Expo Account Dashboard](https://expo.dev)
- [Android APK Installation Guide](https://support.google.com/android/answer/9064445)

