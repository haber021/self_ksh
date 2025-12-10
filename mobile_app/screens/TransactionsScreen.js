import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  ActivityIndicator,
  RefreshControl,
  Alert,
  TouchableOpacity,
} from 'react-native';
import { accountService } from '../services/api';
import { colors } from '../constants/colors';

export default function TransactionsScreen() {
  const [transactions, setTransactions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [hasMore, setHasMore] = useState(true);
  const [pagination, setPagination] = useState(null);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    loadTransactions();
  }, []);

  const loadTransactions = async (pageNum = 1, append = false) => {
    try {
      const response = await accountService.getTransactionHistory(pageNum, 10);
      if (response.success) {
        if (append) {
          setTransactions([...transactions, ...response.transactions]);
        } else {
          setTransactions(response.transactions);
        }
        setPagination(response.pagination);
        setHasMore(response.pagination.has_next);
      }
    } catch (error) {
      Alert.alert('Error', error.toString());
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  };

  const handleRefresh = () => {
    setRefreshing(true);
    setPage(1);
    setShowAll(false);
    loadTransactions(1, false);
  };

  const loadMore = () => {
    if (!loading && hasMore && showAll) {
      const nextPage = page + 1;
      setPage(nextPage);
      loadTransactions(nextPage, true);
    }
  };

  const handleViewAll = async () => {
    setShowAll(true);
    setLoading(true);
    // Load all transactions starting from page 1
    setPage(1);
    await loadTransactions(1, false);
  };

  const formatCurrency = (amount) => {
    const num = parseFloat(amount || 0);
    return `₱${num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };

  const formatDateTime = (dateString) => {
    const date = new Date(dateString);
    return date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const getPaymentMethodStyle = (paymentMethod) => {
    switch (paymentMethod) {
      case 'debit':
        return { backgroundColor: colors.debit, label: 'DEBIT' };
      case 'credit':
        return { backgroundColor: colors.credit, label: 'CREDIT' };
      case 'cash':
        return { backgroundColor: colors.cash, label: 'CASH' };
      default:
        return { backgroundColor: colors.muted, label: 'OTHER' };
    }
  };

  const getStatusStyle = (status) => {
    switch (status) {
      case 'completed':
        return { backgroundColor: colors.success, label: 'COMPLETED' };
      case 'pending':
        return { backgroundColor: colors.warning, label: 'PENDING' };
      case 'cancelled':
        return { backgroundColor: colors.error, label: 'CANCELLED' };
      default:
        return { backgroundColor: colors.muted, label: status?.toUpperCase() || 'UNKNOWN' };
    }
  };

  const renderTransaction = ({ item }) => {
    const paymentStyle = getPaymentMethodStyle(item.payment_method);
    const statusStyle = getStatusStyle(item.status);

    return (
      <View style={styles.transactionCard}>
        <View style={styles.transactionHeader}>
          <View style={styles.transactionInfo}>
            <View style={styles.transactionNumberRow}>
              <Text style={styles.transactionNumber}>{item.transaction_number}</Text>
              <View style={[styles.statusBadge, { backgroundColor: statusStyle.backgroundColor }]}>
                <Text style={styles.statusBadgeText}>{statusStyle.label}</Text>
              </View>
            </View>
            <Text style={styles.transactionDate}>{formatDateTime(item.created_at)}</Text>
          </View>
          <Text style={styles.transactionAmount}>{formatCurrency(item.total_amount)}</Text>
        </View>
        <View style={styles.transactionDetails}>
          <View style={styles.paymentMethodRow}>
            <View style={[styles.paymentBadge, { backgroundColor: paymentStyle.backgroundColor }]}>
              <Text style={styles.paymentBadgeText}>{paymentStyle.label}</Text>
            </View>
            <Text style={styles.detailText}>
              {item.payment_method_display}
            </Text>
          </View>
          {item.patronage_amount > 0 && (
            <View style={styles.patronageRow}>
              <Text style={styles.patronageLabel}>Patronage:</Text>
              <Text style={styles.patronageAmount}>{formatCurrency(item.patronage_amount)}</Text>
            </View>
          )}
          {item.items && item.items.length > 0 && (
            <Text style={styles.itemsText}>
              {item.items.length} item{item.items.length > 1 ? 's' : ''}
            </Text>
          )}
        </View>
      </View>
    );
  };

  if (loading && transactions.length === 0) {
    return (
      <View style={styles.centered}>
        <ActivityIndicator size="large" color={colors.brand} />
      </View>
    );
  }

  return (
    <View style={styles.container}>
      <FlatList
        data={transactions}
        renderItem={renderTransaction}
        keyExtractor={(item) => item.id.toString()}
        refreshControl={
          <RefreshControl refreshing={refreshing} onRefresh={handleRefresh} />
        }
        onEndReached={showAll ? loadMore : null}
        onEndReachedThreshold={0.5}
        ListEmptyComponent={
          <View style={styles.emptyContainer}>
            <Text style={styles.emptyText}>No transactions found</Text>
          </View>
        }
        ListFooterComponent={
          !showAll && transactions.length >= 10 && hasMore ? (
            <View style={styles.footer}>
              <TouchableOpacity style={styles.viewAllButton} onPress={handleViewAll}>
                <Text style={styles.viewAllButtonText}>View All Transactions</Text>
              </TouchableOpacity>
            </View>
          ) : showAll && hasMore && transactions.length > 0 ? (
            <View style={styles.footer}>
              <ActivityIndicator size="small" color={colors.brand} />
            </View>
          ) : null
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: colors.background,
  },
  centered: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: colors.background,
  },
  transactionCard: {
    backgroundColor: colors.panel,
    margin: 15,
    marginBottom: 0,
    borderRadius: 12,
    padding: 15,
    shadowColor: '#000',
    shadowOffset: { width: 0, height: 2 },
    shadowOpacity: 0.1,
    shadowRadius: 4,
    elevation: 3,
  },
  transactionHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 10,
  },
  transactionInfo: {
    flex: 1,
  },
  transactionNumberRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
    flexWrap: 'wrap',
  },
  transactionNumber: {
    fontSize: 16,
    fontWeight: 'bold',
    color: colors.textPrimary,
    marginRight: 8,
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    marginLeft: 4,
  },
  statusBadgeText: {
    color: colors.textWhite,
    fontSize: 10,
    fontWeight: '600',
    letterSpacing: 0.5,
  },
  transactionDate: {
    fontSize: 14,
    color: colors.textSecondary,
  },
  transactionAmount: {
    fontSize: 20,
    fontWeight: 'bold',
    color: colors.brand,
  },
  transactionDetails: {
    borderTopWidth: 1,
    borderTopColor: colors.borderLight,
    paddingTop: 10,
    marginTop: 10,
  },
  paymentMethodRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 8,
  },
  paymentBadge: {
    paddingHorizontal: 8,
    paddingVertical: 4,
    borderRadius: 4,
    marginRight: 8,
  },
  paymentBadgeText: {
    color: colors.textWhite,
    fontSize: 10,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  detailText: {
    fontSize: 14,
    color: colors.textSecondary,
    flex: 1,
  },
  patronageRow: {
    flexDirection: 'row',
    alignItems: 'center',
    marginBottom: 4,
  },
  patronageLabel: {
    fontSize: 14,
    color: colors.textSecondary,
    marginRight: 8,
  },
  patronageAmount: {
    fontSize: 14,
    color: colors.brand,
    fontWeight: '600',
  },
  itemsText: {
    fontSize: 14,
    color: colors.accent,
    marginTop: 4,
  },
  emptyContainer: {
    padding: 40,
    alignItems: 'center',
  },
  emptyText: {
    fontSize: 16,
    color: colors.textSecondary,
  },
  footer: {
    padding: 20,
    alignItems: 'center',
  },
  viewAllButton: {
    backgroundColor: colors.brand,
    borderRadius: 8,
    paddingVertical: 12,
    paddingHorizontal: 24,
    alignItems: 'center',
  },
  viewAllButtonText: {
    color: colors.textWhite,
    fontSize: 16,
    fontWeight: '600',
  },
});

