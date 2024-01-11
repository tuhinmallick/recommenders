# Copyright (c) Recommenders contributors.
# Licensed under the MIT License.

import pandas as pd
import numpy as np
import itertools

from scipy.sparse import coo_matrix
import logging

# import default parameters
from recommenders.utils.constants import (
    DEFAULT_USER_COL,
    DEFAULT_ITEM_COL,
    DEFAULT_RATING_COL,
    DEFAULT_PREDICTION_COL,
)


log = logging.getLogger(__name__)


class AffinityMatrix:
    """Generate the user/item affinity matrix from a pandas dataframe and vice versa"""

    def __init__(
        self,
        df,
        items_list=None,
        col_user=DEFAULT_USER_COL,
        col_item=DEFAULT_ITEM_COL,
        col_rating=DEFAULT_RATING_COL,
        col_pred=DEFAULT_PREDICTION_COL,
        save_path=None,
    ):
        """Initialize class parameters

        Args:
            df (pandas.DataFrame): a dataframe containing the data
            items_list (numpy.ndarray): a list of unique items to use (if provided)
            col_user (str): default name for user column
            col_item (str): default name for item column
            col_rating (str): default name for rating columns
            save_path (str): default path to save item/user maps
        """
        self.df = df  # dataframe
        self.items_list = items_list  # list of unique items

        # pandas DF parameters
        self.col_item = col_item
        self.col_user = col_user
        self.col_rating = col_rating
        self.col_pred = col_pred

        # Options to save the model for future use
        self.save_path = save_path

    def _gen_index(self):
        """
        Generate the user/item index:
        map_users, map_items: dictionaries mapping the original user/item index to matrix indices
        map_back_users, map_back_items: dictionaries to map back the matrix elements to the original
        dataframe indices

        Basic mechanics:
        As a first step we retieve the unique elements in the dataset. In this way we can take care
        of either completely missing rows (a user with no ratings) or completely missing columns
        (an item that has not being reviewed by anyone). The original indices in the dataframe are
        then mapped to an ordered, contiguous integer series to generate a compact matrix representation.
        Functions to map back to the original indices are also provided and can be saved in order to use
        a pretrained model.
        """
        # sort entries by user index
        self.df_ = self.df.sort_values(by=[self.col_user])

        # find unique user and item index
        unique_users = self.df_[self.col_user].unique()

        if self.items_list is not None:
            unique_items = self.items_list  # use this list if provided
        else:
            unique_items = self.df_[
                self.col_item
            ].unique()  # otherwise use unique items from DF

        self.Nusers = len(unique_users)
        self.Nitems = len(unique_items)

        # create a dictionary to map unique users/items to hashed values to generate the matrix
        self.map_users = {x: i for i, x in enumerate(unique_users)}
        self.map_items = {x: i for i, x in enumerate(unique_items)}

        # map back functions used to get back the original dataframe
        self.map_back_users = dict(enumerate(unique_users))
        self.map_back_items = dict(enumerate(unique_items))

        self.df_.loc[:, "hashedItems"] = self.df_[self.col_item].map(self.map_items)
        self.df_.loc[:, "hashedUsers"] = self.df_[self.col_user].map(self.map_users)

        # optionally save the inverse dictionary to work with trained models
        if self.save_path is not None:

            np.save(self.save_path + "/user_dict", self.map_users)
            np.save(self.save_path + "/item_dict", self.map_items)

            np.save(self.save_path + "/user_back_dict", self.map_back_users)
            np.save(self.save_path + "/item_back_dict", self.map_back_items)

    def gen_affinity_matrix(self):
        """Generate the user/item affinity matrix.

        As a first step, two new columns are added to the input DF, containing the index maps
        generated by the gen_index() method. The new indices, together with the ratings, are
        then used to generate the user/item affinity matrix using scipy's sparse matrix method
        coo_matrix; for reference see:
        https://docs.scipy.org/doc/scipy/reference/generated/scipy.sparse.coo_matrix.html.
        The input format is: `coo_matrix((data, (rows, columns)), shape=(rows, columns))`

        Returns:
            scipy.sparse.coo_matrix: User-affinity matrix of dimensions (Nusers, Nitems) in numpy format.
            Unrated movies are assigned a value of 0.
        """

        log.info("Generating the user/item affinity matrix...")

        self._gen_index()

        ratings = self.df_[self.col_rating]  # ratings
        itm_id = self.df_["hashedItems"]  # itm_id serving as columns
        usr_id = self.df_["hashedUsers"]  # usr_id serving as rows

        # generate a sparse matrix representation using scipy's coo_matrix and convert to array format
        self.AM = coo_matrix(
            (ratings, (usr_id, itm_id)), shape=(self.Nusers, self.Nitems)
        ).toarray()

        zero = (self.AM == 0).sum()  # number of unrated items
        total = self.AM.shape[0] * self.AM.shape[1]  # number of elements in the matrix
        sparsness = zero / total * 100  # Percentage of zeros in the matrix

        log.info("Matrix generated, sparseness percentage: %d" % sparsness)

        return self.AM, self.map_users, self.map_items

    def map_back_sparse(self, X, kind):
        """Map back the user/affinity matrix to a pd dataframe

        Args:
            X (numpy.ndarray, int32): user/item affinity matrix
            kind (string): specify if the output values are ratings or predictions
        Returns:
            pandas.DataFrame: the generated pandas dataframe
        """
        m, n = X.shape

        # 1) Create a DF from a sparse matrix
        # obtain the non zero items
        items = [np.asanyarray(np.where(X[i, :] != 0)).flatten() for i in range(m)]
        ratings = [X[i, items[i]] for i in range(m)]  # obtain the non-zero ratings

        # Creates user ids following the DF format
        userids = []
        for i in range(0, m):
            userids.extend([i] * len(items[i]))

        # Flatten the lists to follow the DF input format
        items = list(itertools.chain.from_iterable(items))
        ratings = list(itertools.chain.from_iterable(ratings))

        col_out = self.col_rating if kind == "ratings" else self.col_pred
        # create a df
        out_df = pd.DataFrame.from_dict(
            {self.col_user: userids, self.col_item: items, col_out: ratings}
        )

        # 2) map back user/item ids to their original value

        out_df[self.col_user] = out_df[self.col_user].map(self.map_back_users)
        out_df[self.col_item] = out_df[self.col_item].map(self.map_back_items)

        return out_df
