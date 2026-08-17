import { StatusBar } from 'expo-status-bar';
import * as ImagePicker from 'expo-image-picker';
import { useMemo, useState } from 'react';
import {
  ActivityIndicator,
  Alert,
  Image,
  Platform,
  Pressable,
  SafeAreaView,
  ScrollView,
  StyleSheet,
  Text,
  View,
} from 'react-native';

const API_URL = (process.env.EXPO_PUBLIC_API_URL || 'http://localhost:8000').replace(/\/$/, '');

function confidenceBand(value) {
  if (value == null) return 'unmatched';
  if (value >= 0.82) return 'high';
  if (value >= 0.45) return 'low';
  return 'unmatched';
}

function confidenceLabel(value) {
  if (value == null) return 'No match';
  return `${Math.round(value * 100)}% match`;
}

function imageFile(asset) {
  const extension = asset.fileName?.split('.').pop()?.toLowerCase() || 'jpg';
  const type = asset.mimeType || (extension === 'png' ? 'image/png' : 'image/jpeg');
  return {
    uri: asset.uri,
    name: asset.fileName || `shelf.${extension}`,
    type,
  };
}

export default function App() {
  const [photo, setPhoto] = useState(null);
  const [scan, setScan] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const detections = scan?.detections || [];
  const summary = scan?.summary;
  const reviewCount = useMemo(
    () => detections.filter((item) => confidenceBand(item.match_confidence) !== 'high').length,
    [detections],
  );

  async function pickFromLibrary() {
    const permission = await ImagePicker.requestMediaLibraryPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Photo access needed', 'Allow photo access to choose a bookshelf image.');
      return;
    }
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'],
      quality: 0.9,
    });
    if (!result.canceled) selectPhoto(result.assets[0]);
  }

  async function takePhoto() {
    const permission = await ImagePicker.requestCameraPermissionsAsync();
    if (!permission.granted) {
      Alert.alert('Camera access needed', 'Allow camera access to photograph your bookshelf.');
      return;
    }
    const result = await ImagePicker.launchCameraAsync({
      mediaTypes: ['images'],
      quality: 0.9,
    });
    if (!result.canceled) selectPhoto(result.assets[0]);
  }

  function selectPhoto(asset) {
    setPhoto(asset);
    setScan(null);
    setError('');
  }

  async function scanShelf() {
    if (!photo || loading) return;
    setLoading(true);
    setError('');
    setScan(null);

    try {
      const body = new FormData();
      body.append('image', imageFile(photo));
      const response = await fetch(`${API_URL}/api/scans/`, {
        method: 'POST',
        body,
        // Let fetch supply the multipart boundary.
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload.detail || `Scan failed (${response.status})`);
      }
      setScan(payload);
    } catch (requestError) {
      const hint =
        Platform.OS === 'android' && API_URL.includes('localhost')
          ? ' On a phone, set EXPO_PUBLIC_API_URL to your computer’s LAN IP.'
          : '';
      setError(`${requestError.message || 'Could not scan this photo.'}${hint}`);
    } finally {
      setLoading(false);
    }
  }

  function reset() {
    setPhoto(null);
    setScan(null);
    setError('');
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.header}>
          <View>
            <Text style={styles.brand}>SHELFIE</Text>
            <Text style={styles.title}>Shelf to library.</Text>
          </View>
          <View style={styles.localBadge}>
            <View style={styles.localDot} />
            <Text style={styles.localText}>Local detection</Text>
          </View>
        </View>

        {!photo ? (
          <View style={styles.heroCard}>
            <View style={styles.bookIcon}>
              <View style={[styles.book, styles.bookOne]} />
              <View style={[styles.book, styles.bookTwo]} />
              <View style={[styles.book, styles.bookThree]} />
            </View>
            <Text style={styles.heroTitle}>Scan your bookshelf</Text>
            <Text style={styles.heroBody}>
              Take one clear, straight-on photo. Shelfie will find each spine and identify the books.
            </Text>
            <Pressable style={styles.primaryButton} onPress={takePhoto}>
              <Text style={styles.primaryButtonText}>Take a photo</Text>
            </Pressable>
            <Pressable style={styles.secondaryButton} onPress={pickFromLibrary}>
              <Text style={styles.secondaryButtonText}>Choose from library</Text>
            </Pressable>
            <Text style={styles.privacy}>Spine detection runs locally. Only crops go to Gemini.</Text>
          </View>
        ) : (
          <>
            <View style={styles.photoCard}>
              <Image source={{ uri: photo.uri }} style={styles.preview} resizeMode="cover" />
              {!loading && !scan && (
                <Pressable style={styles.changeButton} onPress={pickFromLibrary}>
                  <Text style={styles.changeButtonText}>Change photo</Text>
                </Pressable>
              )}
              {loading && (
                <View style={styles.loadingOverlay}>
                  <ActivityIndicator size="large" color="#F8F4EA" />
                  <Text style={styles.loadingTitle}>Reading your shelf…</Text>
                  <Text style={styles.loadingText}>Finding spines → reading text → matching catalog</Text>
                </View>
              )}
            </View>

            {!loading && !scan && (
              <Pressable style={styles.primaryButton} onPress={scanShelf}>
                <Text style={styles.primaryButtonText}>Scan this shelf</Text>
              </Pressable>
            )}

            {!!error && (
              <View style={styles.errorCard}>
                <Text style={styles.errorTitle}>We couldn’t process that photo</Text>
                <Text style={styles.errorBody}>{error}</Text>
                <Pressable style={styles.errorAction} onPress={scanShelf}>
                  <Text style={styles.errorActionText}>Try again</Text>
                </Pressable>
              </View>
            )}

            {!!scan && (
              <>
                <View style={styles.summaryCard}>
                  <View>
                    <Text style={styles.summaryTitle}>
                      {detections.length ? `${detections.length} spines found` : 'No books found'}
                    </Text>
                    <Text style={styles.summaryBody}>
                      {summary?.message ||
                        `${summary?.high_confidence || 0} ready · ${reviewCount} need review`}
                    </Text>
                  </View>
                  <View style={styles.metric}>
                    <Text style={styles.metricValue}>
                      {scan.latency_ms == null ? '—' : `${(scan.latency_ms / 1000).toFixed(1)}s`}
                    </Text>
                    <Text style={styles.metricLabel}>latency</Text>
                  </View>
                </View>

                {detections.map((item, index) => {
                  const band = confidenceBand(item.match_confidence);
                  const displayBook = item.matched_book;
                  return (
                    <View key={item.id || index} style={styles.resultCard}>
                      {item.crop_image ? (
                        <Image source={{ uri: item.crop_image }} style={styles.crop} />
                      ) : (
                        <View style={styles.cropFallback}>
                          <Text style={styles.cropFallbackText}>{index + 1}</Text>
                        </View>
                      )}
                      <View style={styles.resultText}>
                        <Text numberOfLines={2} style={styles.bookTitle}>
                          {displayBook?.title || item.raw_title || 'Unreadable spine'}
                        </Text>
                        <Text numberOfLines={1} style={styles.author}>
                          {displayBook?.author || item.raw_author || item.ocr_error || 'Unknown author'}
                        </Text>
                        <View style={[styles.confidence, styles[`confidence_${band}`]]}>
                          <Text style={[styles.confidenceText, styles[`confidenceText_${band}`]]}>
                            {band === 'high' ? 'Ready · ' : 'Review · '}
                            {confidenceLabel(item.match_confidence)}
                          </Text>
                        </View>
                      </View>
                    </View>
                  );
                })}

                <Pressable style={styles.secondaryButton} onPress={reset}>
                  <Text style={styles.secondaryButtonText}>Scan another shelf</Text>
                </Pressable>
              </>
            )}
          </>
        )}
      </ScrollView>
    </SafeAreaView>
  );
}

const colors = {
  ink: '#252A24',
  forest: '#234D3C',
  cream: '#F6F1E7',
  paper: '#FFFCF6',
  sage: '#DDE8DA',
  amber: '#E9B44C',
  red: '#A3483F',
  muted: '#6D736B',
  border: '#DDD8CD',
};

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: colors.cream },
  page: { flexGrow: 1, padding: 20, paddingBottom: 44, gap: 16 },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginTop: 8,
    marginBottom: 6,
  },
  brand: { color: colors.forest, fontSize: 12, fontWeight: '900', letterSpacing: 2.4 },
  title: { color: colors.ink, fontSize: 28, fontWeight: '800', marginTop: 2 },
  localBadge: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    paddingHorizontal: 10,
    paddingVertical: 7,
    borderRadius: 18,
    backgroundColor: colors.sage,
  },
  localDot: { width: 7, height: 7, borderRadius: 4, backgroundColor: colors.forest },
  localText: { color: colors.forest, fontSize: 11, fontWeight: '700' },
  heroCard: {
    flex: 1,
    minHeight: 530,
    backgroundColor: colors.paper,
    borderRadius: 28,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 26,
    justifyContent: 'center',
    alignItems: 'center',
    shadowColor: '#1E241E',
    shadowOpacity: 0.08,
    shadowRadius: 24,
    shadowOffset: { width: 0, height: 8 },
    elevation: 3,
  },
  bookIcon: { height: 116, width: 150, flexDirection: 'row', alignItems: 'flex-end', marginBottom: 30 },
  book: { borderRadius: 4, borderWidth: 3, borderColor: colors.ink, marginHorizontal: 3 },
  bookOne: { width: 36, height: 102, backgroundColor: colors.amber, transform: [{ rotate: '-5deg' }] },
  bookTwo: { width: 39, height: 112, backgroundColor: colors.forest },
  bookThree: { width: 42, height: 90, backgroundColor: '#C96D55', transform: [{ rotate: '5deg' }] },
  heroTitle: { color: colors.ink, fontSize: 26, fontWeight: '800', textAlign: 'center' },
  heroBody: {
    color: colors.muted,
    fontSize: 15,
    lineHeight: 22,
    textAlign: 'center',
    marginTop: 10,
    marginBottom: 28,
  },
  primaryButton: {
    width: '100%',
    backgroundColor: colors.forest,
    paddingVertical: 16,
    borderRadius: 16,
    alignItems: 'center',
  },
  primaryButtonText: { color: '#FFFFFF', fontSize: 16, fontWeight: '800' },
  secondaryButton: {
    width: '100%',
    backgroundColor: 'transparent',
    paddingVertical: 15,
    borderRadius: 16,
    borderWidth: 1.5,
    borderColor: colors.forest,
    alignItems: 'center',
    marginTop: 11,
  },
  secondaryButtonText: { color: colors.forest, fontSize: 15, fontWeight: '800' },
  privacy: { color: colors.muted, fontSize: 11, textAlign: 'center', marginTop: 20 },
  photoCard: {
    position: 'relative',
    overflow: 'hidden',
    borderRadius: 22,
    backgroundColor: colors.ink,
    minHeight: 260,
  },
  preview: { width: '100%', height: 300 },
  changeButton: {
    position: 'absolute',
    right: 12,
    bottom: 12,
    backgroundColor: 'rgba(255,252,246,0.94)',
    paddingVertical: 9,
    paddingHorizontal: 13,
    borderRadius: 12,
  },
  changeButtonText: { color: colors.ink, fontWeight: '800', fontSize: 12 },
  loadingOverlay: {
    ...StyleSheet.absoluteFillObject,
    backgroundColor: 'rgba(24,48,38,0.86)',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 28,
  },
  loadingTitle: { color: colors.paper, fontSize: 21, fontWeight: '800', marginTop: 16 },
  loadingText: { color: '#D8E2D8', fontSize: 12, textAlign: 'center', marginTop: 7 },
  errorCard: {
    borderRadius: 18,
    padding: 18,
    backgroundColor: '#F7E2DE',
    borderWidth: 1,
    borderColor: '#E7B9B2',
  },
  errorTitle: { color: colors.red, fontWeight: '800', fontSize: 16 },
  errorBody: { color: '#763D37', marginTop: 6, lineHeight: 20 },
  errorAction: { alignSelf: 'flex-start', marginTop: 12 },
  errorActionText: { color: colors.red, fontWeight: '900' },
  summaryCard: {
    backgroundColor: colors.forest,
    borderRadius: 20,
    padding: 18,
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  summaryTitle: { color: '#FFFFFF', fontSize: 18, fontWeight: '800' },
  summaryBody: { color: '#CFE0D8', marginTop: 4, maxWidth: 250 },
  metric: { alignItems: 'flex-end' },
  metricValue: { color: colors.amber, fontSize: 18, fontWeight: '900' },
  metricLabel: { color: '#CFE0D8', fontSize: 10, marginTop: 1 },
  resultCard: {
    flexDirection: 'row',
    backgroundColor: colors.paper,
    borderRadius: 18,
    borderWidth: 1,
    borderColor: colors.border,
    padding: 12,
    gap: 14,
    alignItems: 'center',
  },
  crop: { width: 48, height: 92, borderRadius: 8, backgroundColor: colors.sage },
  cropFallback: {
    width: 48,
    height: 92,
    borderRadius: 8,
    backgroundColor: colors.sage,
    alignItems: 'center',
    justifyContent: 'center',
  },
  cropFallbackText: { color: colors.forest, fontWeight: '900', fontSize: 18 },
  resultText: { flex: 1 },
  bookTitle: { color: colors.ink, fontSize: 16, lineHeight: 20, fontWeight: '800' },
  author: { color: colors.muted, fontSize: 13, marginTop: 5 },
  confidence: {
    alignSelf: 'flex-start',
    borderRadius: 12,
    paddingHorizontal: 9,
    paddingVertical: 5,
    marginTop: 10,
  },
  confidence_high: { backgroundColor: colors.sage },
  confidence_low: { backgroundColor: '#F8E8C5' },
  confidence_unmatched: { backgroundColor: '#F2DEDA' },
  confidenceText: { fontSize: 11, fontWeight: '800' },
  confidenceText_high: { color: colors.forest },
  confidenceText_low: { color: '#805C18' },
  confidenceText_unmatched: { color: colors.red },
});
