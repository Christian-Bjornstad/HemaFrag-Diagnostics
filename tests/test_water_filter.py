from core.utils import is_water_file


def test_water_file_prefix_v_token_is_filtered():
    assert is_water_file("v_IgK_19012026_E10_H9C0U3IH.fsa")
    assert is_water_file("v_TCRb_C_03022026_C12_H9C0VCGF.fsa")
    assert is_water_file("00001_abcd1234_v_TCRg_A_010126_A01_RUN.fsa")


def test_water_filter_does_not_match_patient_ids_with_v_inside_token():
    assert not is_water_file("25OUM04224_KDE_200326_A05_H9H1DHZK.fsa")
    assert not is_water_file("26OUM00877_TCRg_A_22012026_H01_H9C0U3SF.fsa")
    assert not is_water_file("25OUM07652_Kde_150525_C12_H9C0ZJ8K.fsa")
