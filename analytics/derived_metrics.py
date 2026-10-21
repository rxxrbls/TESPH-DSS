import pandas as pd

class DerivedMetricsCalculator:
    def __init__(self, fact_sales: pd.DataFrame, dim_order: pd.DataFrame):
        self.fact_sales = fact_sales
        self.dim_order = dim_order

    def get_gross_revenue(self) -> pd.DataFrame:
        """
        Calculates Gross Revenue per product/date based on TA explicit instructions:
        - Primary Field: total_amount_paid_by_buyer (Total Buyer Payment)
        - Order Status Inclusions: Include strictly Completed orders. Exclude Cancelled or Unpaid.
        """
        # Join with dim_order to filter status
        df = self.fact_sales.merge(self.dim_order[['Order ID', 'Order Status']], on='Order ID', how='left')
        
        # Filter strictly Completed
        df_completed = df[df['Order Status'].str.lower() == 'completed'].copy()
        
        # We assume 'Total Buyer Payment' is the column for total_amount_paid_by_buyer
        df_completed['gross_revenue'] = df_completed['Total Buyer Payment']
        
        return df_completed

    def get_gross_demand(self) -> pd.DataFrame:
        """
        Calculates Gross Demand per product/date based on TA explicit instructions:
        - Demand Calculations: Include both Completed and Returned/Refunded orders.
        - Gross Demand: Count total items ordered using number_of_items (Quantity) before returns.
        """
        df = self.fact_sales.merge(self.dim_order[['Order ID', 'Order Status', 'Return / Refund Status']], on='Order ID', how='left')
        
        status = df['Order Status'].astype('string').str.strip().str.casefold()
        return_status = df['Return / Refund Status'].astype('string').str.strip().str.casefold()
        is_completed = df.get('is_completed', status.eq('completed'))
        is_returned = df.get(
            'is_returned',
            status.isin(['returned', 'refunded'])
            | return_status.isin(['returned', 'refunded', 'request approved', 'dispute resolved']),
        )
        df_demand = df[is_completed.fillna(False) | is_returned.fillna(False)].copy()
        
        df_demand['gross_demand'] = df_demand['Quantity']
        
        return df_demand

    def get_net_revenue_and_inventory(self) -> pd.DataFrame:
        """
        Calculates Net Revenue & Inventory based on TA explicit instructions:
        - Net Revenue & Inventory: Deduct returned quantities using number_of_items_returned 
          (Returned quantity) from total units to reflect realized net sales and restocked inventory.
        """
        df = self.get_gross_revenue()
        
        # Deduct returned quantities
        df['net_quantity'] = df['Quantity'] - df['Returned quantity'].fillna(0)
        
        return df

    def calculate_sales_velocity(self) -> pd.DataFrame:
        """
        Calculates Sales Velocity.
        NOTE: Formula pending TA approval. (Do not invent formulas during coding).
        """
        raise NotImplementedError("Sales Velocity formula is pending TA approval.")

    def calculate_dsi(self) -> pd.DataFrame:
        """
        Calculates 60-day Days Sales of Inventory (DSI).
        NOTE: Formula pending TA approval. (Do not invent formulas during coding).
        """
        raise NotImplementedError("60-day DSI formula is pending TA approval.")

    @staticmethod
    def calculate_stock_out_frequency(stock_history_df: pd.DataFrame) -> pd.DataFrame:
        """Approved percentage of valid observed product-days at net stock <= 0.

        Compatibility input Current Stock must represent net sellable stock.
        The caller supplies the observation period by filtering this frame.
        """
        required = {"product_key", "Stock As-Of Date", "Current Stock"}
        missing = required.difference(stock_history_df.columns)
        if missing:
            raise ValueError(f"Missing stock-history columns: {sorted(missing)}")
        from mca_inputs import calculate_stock_out_frequency
        if stock_history_df.empty:
            return pd.DataFrame(columns=["product_key", "stock_out_frequency"])
        dates = pd.to_datetime(stock_history_df["Stock As-Of Date"], errors="raise")
        return calculate_stock_out_frequency(
            stock_history_df, period_start=dates.min(), period_end=dates.max(),
            identifier="product_key", date="Stock As-Of Date", stock="Current Stock",
        ).rename(columns={"Stock-Out Frequency": "stock_out_frequency"})[["product_key", "stock_out_frequency"]]

    def calculate_stockout_frequency(self) -> pd.DataFrame:
        """Orders alone cannot provide daily stock history."""
        raise NotImplementedError("Supply daily net-sellable stock history to calculate_stock_out_frequency.")

