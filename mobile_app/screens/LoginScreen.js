import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Alert,
  ActivityIndicator,
  KeyboardAvoidingView,
  Platform,
  ScrollView,
} from 'react-native';
import { authService } from '../services/api';
import { API_BASE_URL } from '../config';
import { colors } from '../constants/colors';

export default function LoginScreen({ navigation }) {
  const [username, setUsername] = useState('');
  const [pin, setPin] = useState('');
  const [loading, setLoading] = useState(false);
  const [checkingAuth, setCheckingAuth] = useState(true);
  const [checkingConnection, setCheckingConnection] = useState(false);
  const [connectionStatus, setConnectionStatus] = useState(null);

  useEffect(() => {
    // Check if user is already logged in
    checkAuth();
  }, []);

  const checkAuth = async () => {
    try {
      const member = await authService.getStoredMember();
      if (member) {
        // User is already logged in, navigate to main tabs
        navigation.replace('Main');
      }
    } catch (error) {
      console.log('No stored auth');
    } finally {
      setCheckingAuth(false);
    }
  };

  const testConnection = async () => {
    setCheckingConnection(true);
    setConnectionStatus(null);
    try {
      const result = await authService.checkConnectionDetailed();
      if (result.connected) {
        setConnectionStatus('connected');
        Alert.alert(
          'Connection Success', 
          `✓ Connected to server\n\nURL: ${result.url}\n\nYou can now login.`
        );
      } else {
        setConnectionStatus('failed');
        Alert.alert(
          'Connection Failed',
          result.error || `Cannot reach server at ${result.url}\n\nPlease check:\n• Your internet connection\n• Server URL in config.js\n• Server is running\n• Both devices on same network (if using local IP)`
        );
      }
    } catch (error) {
      setConnectionStatus('failed');
      Alert.alert(
        'Connection Error',
        `Error: ${error.message || 'Unknown error'}\n\nServer URL: ${API_BASE_URL}\n\nTroubleshooting:\n1. Check if Django server is running\n2. Verify server URL in config.js\n3. Ensure both devices are on same network\n4. Check firewall settings`
      );
    } finally {
      setCheckingConnection(false);
    }
  };

  const handleLogin = async () => {
    if (!username.trim() || !pin.trim()) {
      Alert.alert('Missing Information', 'Please enter both username and PIN');
      return;
    }

    if (pin.length !== 4 || !/^\d+$/.test(pin)) {
      Alert.alert('Invalid PIN', 'PIN must be exactly 4 digits');
      return;
    }

    setLoading(true);
    try {
      const result = await authService.login(username.trim(), pin);
      if (result.success) {
        // Show success message
        Alert.alert('Login Successful', result.message || 'Welcome!', [
          {
            text: 'OK',
            onPress: () => navigation.replace('Main'),
          },
        ]);
      }
    } catch (error) {
      // Show user-friendly error message
      const errorMessage = typeof error === 'string' ? error : error.message || 'Login failed';
      Alert.alert(
        'Login Failed',
        errorMessage,
        [
          {
            text: 'Test Connection',
            onPress: testConnection,
            style: 'default',
          },
          {
            text: 'OK',
            style: 'cancel',
          },
        ]
      );
    } finally {
      setLoading(false);
    }
  };

  if (checkingAuth) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={styles.container}
      behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
    >
      <ScrollView
        contentContainerStyle={styles.scrollContent}
        keyboardShouldPersistTaps="handled"
      >
        <View style={styles.content}>
          <Text style={styles.title}>Coop Kiosk</Text>
          <Text style={styles.subtitle}>Member Login</Text>

          {/* Server URL Display */}
          <View style={styles.serverInfo}>
            <Text style={styles.serverLabel}>Server:</Text>
            <Text style={styles.serverUrl} numberOfLines={1}>
              {API_BASE_URL}
            </Text>
            <TouchableOpacity
              style={styles.testButton}
              onPress={testConnection}
              disabled={checkingConnection}
            >
              {checkingConnection ? (
                <ActivityIndicator size="small" color={colors.brand} />
              ) : (
                <Text style={styles.testButtonText}>Test Connection</Text>
              )}
            </TouchableOpacity>
          </View>

          <View style={styles.form}>
            <Text style={styles.label}>Username</Text>
            <TextInput
              style={styles.input}
              placeholder="Enter username"
              value={username}
              onChangeText={setUsername}
              autoCapitalize="none"
              autoCorrect={false}
              keyboardType="default"
              editable={!loading}
              placeholderTextColor={colors.textMuted}
            />

            <Text style={styles.label}>PIN</Text>
            <TextInput
              style={styles.input}
              placeholder="Enter 4-digit PIN"
              value={pin}
              onChangeText={setPin}
              secureTextEntry
              keyboardType="numeric"
              maxLength={4}
              editable={!loading}
              placeholderTextColor={colors.textMuted}
            />

            <TouchableOpacity
              style={[styles.button, (loading || !username.trim() || !pin.trim()) && styles.buttonDisabled]}
              onPress={handleLogin}
              disabled={loading || !username.trim() || !pin.trim()}
            >
              {loading ? (
                <ActivityIndicator color={colors.textWhite} />
              ) : (
                <Text style={styles.buttonText}>Login</Text>
              )}
            </TouchableOpacity>

            {connectionStatus === 'failed' && (
              <View style={styles.errorBox}>
                <Text style={styles.errorText}>
                  ⚠️ Connection issue detected. Please check your server settings.
                </Text>
              </View>
            )}
          </View>
        </View>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  scrollContent: {
    flexGrow: 1,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  content: {
    flex: 1,
    justifyContent: 'center',
    padding: 20,
  },
  title: {
    fontSize: 32,
    fontWeight: 'bold',
    textAlign: 'center',
    marginBottom: 8,
    color: colors.textPrimary,
  },
  subtitle: {
    fontSize: 18,
    textAlign: 'center',
    marginBottom: 20,
    color: colors.textSecondary,
  },
  serverInfo: {
    backgroundColor: colors.panel,
    borderRadius: 8,
    padding: 12,
    marginBottom: 20,
    borderWidth: 1,
    borderColor: colors.border,
  },
  serverLabel: {
    fontSize: 12,
    color: colors.textSecondary,
    marginBottom: 4,
  },
  serverUrl: {
    fontSize: 14,
    color: colors.textPrimary,
    fontWeight: '500',
    marginBottom: 8,
  },
  testButton: {
    alignSelf: 'flex-start',
    paddingVertical: 6,
    paddingHorizontal: 12,
    borderRadius: 6,
    backgroundColor: colors.borderLight,
  },
  testButtonText: {
    color: colors.brand,
    fontSize: 14,
    fontWeight: '600',
  },
  form: {
    width: '100%',
  },
  label: {
    fontSize: 16,
    fontWeight: '600',
    marginBottom: 8,
    color: colors.textPrimary,
  },
  input: {
    backgroundColor: colors.panel,
    borderWidth: 1,
    borderColor: colors.border,
    borderRadius: 8,
    padding: 15,
    fontSize: 16,
    marginBottom: 20,
    color: colors.textPrimary,
  },
  button: {
    backgroundColor: colors.brand,
    borderRadius: 8,
    padding: 15,
    alignItems: 'center',
    marginTop: 10,
  },
  buttonDisabled: {
    opacity: 0.6,
  },
  buttonText: {
    color: colors.textWhite,
    fontSize: 18,
    fontWeight: '600',
  },
  errorBox: {
    backgroundColor: '#fff3cd',
    borderWidth: 1,
    borderColor: colors.warning,
    borderRadius: 8,
    padding: 12,
    marginTop: 15,
  },
  errorText: {
    color: '#856404',
    fontSize: 14,
    textAlign: 'center',
  },
});

